# monster_hunter.py
import asyncio
import json
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import stats_db
import economie_db
import inventory_db
import equipement_db
import combat_manager
from combat_manager import CombatSession

load_dotenv()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, "armes.json"), encoding="utf-8") as f:
    CATALOGUE_ARMES = {a["id"]: a for a in json.load(f)}
with open(os.path.join(BASE_DIR, "armures.json"), encoding="utf-8") as f:
    CATALOGUE_ARMURES = {a["id"]: a for a in json.load(f)}

CATALOGUE_POTIONS = {
    "potion_soin": {"nom": "Potion de soin", "soin": 30, "prix": 50},
    "grande_potion_soin": {"nom": "Grande potion de soin", "soin": 70, "prix": 120},
}


class GuildHuntState:
    """État de chasse pour un serveur donné."""

    def __init__(self):
        self.session: CombatSession | None = None
        self.monstre_en_attente = None      # dict brut du monstre si il attend d'être chassé
        self.channel_attente = None
        self.event_chasse_lancee = asyncio.Event()
        self.spawn_task = None
        self.vocal_channel_id = None  # None = tous les salons vocaux, sinon ID précis à surveiller


class MonsterHunter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.etats_guildes: dict[int, GuildHuntState] = {}

    def _etat(self, guild_id):
        if guild_id not in self.etats_guildes:
            self.etats_guildes[guild_id] = GuildHuntState()
        return self.etats_guildes[guild_id]

    # ------------------------------------------------------------------ #
    # Boucle de spawn (une par serveur, lancée dans un salon fixe)
    # ------------------------------------------------------------------ #

    def demarrer_boucle_spawn(self, guild, channel, vocal_channel_id=None):
        """
        À appeler une fois au démarrage du bot (ou via une commande !init_chasse).
        vocal_channel_id: si précisé, seul ce salon vocal (par ID) est surveillé pour
        déclencher le spawn ; sinon tous les salons vocaux du serveur sont pris en compte.
        """
        etat = self._etat(guild.id)
        if etat.spawn_task and not etat.spawn_task.done():
            return
        etat.channel_attente = channel
        etat.vocal_channel_id = vocal_channel_id
        etat.spawn_task = asyncio.create_task(self._boucle_spawn(guild, channel))

    def _quelquun_en_vocal(self, guild):
        etat = self._etat(guild.id)
        if etat.vocal_channel_id:
            vc = guild.get_channel(etat.vocal_channel_id)
            salons = [vc] if vc else []
        else:
            salons = guild.voice_channels
        for vc in salons:
            if any(not m.bot for m in vc.members):
                return True
        return False

    async def spawner_monstre(self, guild, channel, monstre_data=None):
        """
        Fonction réutilisable : fait apparaître un monstre dans `channel` et attend
        soit qu'il soit chassé (puis que le combat se termine), soit qu'il s'en aille
        faute de chasseurs après TIMEOUT_CHASSE. Utilisée par la boucle de spawn
        automatique ET par la commande admin `!spawn_admin`.

        Retourne False si un monstre ou un combat est déjà en cours sur ce serveur
        (pas de spawn effectué), True sinon.
        """
        etat = self._etat(guild.id)

        if etat.monstre_en_attente is not None or (etat.session and not etat.session.termine):
            return False

        data = monstre_data or combat_manager.monstre_aleatoire()
        etat.monstre_en_attente = data
        etat.event_chasse_lancee.clear()
        await channel.send(
            f"🐾 Un **{data['nom']}** est apparu ! Utilisez `!chasse` pour l'affronter "
            f"(il partira dans {combat_manager.TIMEOUT_CHASSE // 60} minutes si personne ne vient)."
        )

        try:
            await asyncio.wait_for(
                etat.event_chasse_lancee.wait(), timeout=combat_manager.TIMEOUT_CHASSE
            )
        except asyncio.TimeoutError:
            # personne n'est venu chasser le monstre à temps
            etat.monstre_en_attente = None
            await channel.send(f"{data['nom']} s'en va, personne n'est venu le chasser à temps.")
            return True

        # --- Un combat a démarré, on attend sa résolution ---
        session = etat.session
        while session and not session.termine:
            await asyncio.sleep(2)

        etat.monstre_en_attente = None
        return True

    async def _boucle_spawn(self, guild, channel):
        etat = self._etat(guild.id)
        while True:
            # On attend qu'au moins un joueur (non-bot) soit en vocal
            while not self._quelquun_en_vocal(guild):
                await asyncio.sleep(60)

            await asyncio.sleep(combat_manager.INTERVALLE_SPAWN)

            if not self._quelquun_en_vocal(guild):
                continue  # personne n'est resté en vocal, on retente au prochain cycle

            await self.spawner_monstre(guild, channel)
            await asyncio.sleep(combat_manager.DELAI_APRES_COMBAT)
            # on ne remet pas etat.session à None ici : !loot doit encore pouvoir
            # être utilisé jusqu'à la prochaine chasse, il sera écrasé au prochain !chasse

    # ------------------------------------------------------------------ #
    # Commandes de chasse / combat
    # ------------------------------------------------------------------ #

    @commands.command(name="chasse")
    async def chasse(self, ctx):
        etat = self._etat(ctx.guild.id)
        await ctx.message.delete()

        if etat.monstre_en_attente is None:
            m = await ctx.send("Aucun monstre n'est disponible pour le moment.")
            await asyncio.sleep(5)
            await m.delete()
            return

        if etat.session is None or etat.session.termine:
            etat.session = CombatSession(ctx.guild.id, ctx.channel, etat.monstre_en_attente)
            etat.session.rejoindre(ctx.author.id)
            etat.session.demarrer()
            etat.event_chasse_lancee.set()
            await ctx.send(
                f"⚔️ <@{ctx.author.id}> engage le combat contre **{etat.session.monstre.nom}** ! "
                f"Les autres joueurs peuvent rejoindre avec `!chasse`."
            )
        else:
            etat.session.rejoindre(ctx.author.id)
            await ctx.send(f"<@{ctx.author.id}> rejoint la chasse !")

    async def _definir_etat_combat(self, ctx, etat_joueur):
        etat = self._etat(ctx.guild.id)
        await ctx.message.delete()
        session = etat.session
        if session is None or session.termine:
            m = await ctx.send("Aucun combat en cours.")
            await asyncio.sleep(5)
            await m.delete()
            return
        if str(ctx.author.id) not in session.participants:
            m = await ctx.send("Vous ne participez pas à ce combat, faites `!chasse` d'abord.")
            await asyncio.sleep(5)
            await m.delete()
            return
        session.definir_etat(ctx.author.id, etat_joueur)

    @commands.command(name="attaque")
    async def attaque(self, ctx):
        await self._definir_etat_combat(ctx, "attaque")

    @commands.command(name="esquive")
    async def esquive(self, ctx):
        await self._definir_etat_combat(ctx, "esquive")

    @commands.command(name="soin")
    async def soin(self, ctx):
        etat = self._etat(ctx.guild.id)
        await ctx.message.delete()
        session = etat.session
        if session is None or session.termine:
            return
        user_id = str(ctx.author.id)
        if user_id not in session.participants or stats_db.is_dead(user_id):
            return

        nouvelle_qte, _ = inventory_db.use_item(user_id, "potion_soin", quantity=1)
        if nouvelle_qte is None:
            m = await ctx.send(f"<@{user_id}> n'a pas de potion de soin !")
            session.messages_a_supprimer.append(m)
            return

        soin_montant = CATALOGUE_POTIONS["potion_soin"]["soin"]
        nouveau_hp = stats_db.heal(user_id, soin_montant)
        session.definir_etat(user_id, "soin")
        m = await ctx.send(f"<@{user_id}> se soigne de {soin_montant} PV ({nouveau_hp} PV actuels).")
        session.messages_a_supprimer.append(m)

    @commands.command(name="info_monstre")
    async def info_monstre(self, ctx):
        etat = self._etat(ctx.guild.id)
        await ctx.message.delete()
        session = etat.session
        if session is None or session.termine:
            m = await ctx.send("Aucun combat en cours.")
            await asyncio.sleep(5)
            await m.delete()
            return

        embed = discord.Embed(title=f"{session.monstre.nom}", color=discord.Color.red())
        embed.add_field(name="HP", value=f"{session.monstre.hp}/{session.monstre.hp_max}", inline=False)
        if session.monstre.image:
            embed.set_thumbnail(url=session.monstre.image)

        for uid in session.participants:
            stats = stats_db.get_stats(uid)
            etat_j = session.etats.get(uid, "attaque")
            statut = "💀 Mort" if stats_db.is_dead(uid) else f"{stats['hp']}/{stats['hp_max']} PV ({etat_j})"
            embed.add_field(name=f"Joueur {uid}", value=statut, inline=True)

        msg = await ctx.send(embed=embed)
        session.messages_a_supprimer.append(msg)

    @commands.command(name="loot")
    async def loot(self, ctx):
        etat = self._etat(ctx.guild.id)
        await ctx.message.delete()
        session = etat.session
        if session is None or not session.termine:
            m = await ctx.send("Il n'y a rien à looter pour le moment.")
            await asyncio.sleep(5)
            await m.delete()
            return

        items = session.loot(ctx.author.id)
        if items is None:
            await ctx.send(f"<@{ctx.author.id}> ne peut pas looter (mort ou non participant).")
        elif not items:
            await ctx.send(f"<@{ctx.author.id}> n'a rien trouvé cette fois-ci.")
        else:
            await ctx.send(f"<@{ctx.author.id}> a récupéré : {', '.join(items)}")

    # ------------------------------------------------------------------ #
    # Inventaire / équipement
    # ------------------------------------------------------------------ #

    @commands.command(name="inventaire")
    async def inventaire(self, ctx, action: str = None, item_id: str = None):
        user_id = str(ctx.author.id)

        if action == "equiper" and item_id:
            if item_id in CATALOGUE_ARMES:
                possede = inventory_db.get_items(user_id, item_id)
                if possede is None and item_id != "epee_bois":
                    await ctx.send("Vous ne possédez pas cette arme.")
                    return
                equipement_db.equiper_arme(user_id, item_id)
                await ctx.send(f"<@{user_id}> équipe **{CATALOGUE_ARMES[item_id]['nom']}**.")
            elif item_id in CATALOGUE_ARMURES:
                possede = inventory_db.get_items(user_id, item_id)
                if possede is None and item_id != "tunique_tissu":
                    await ctx.send("Vous ne possédez pas cette armure.")
                    return
                equipement_db.equiper_armure(user_id, item_id)
                await ctx.send(f"<@{user_id}> équipe **{CATALOGUE_ARMURES[item_id]['nom']}**.")
            else:
                await ctx.send("Objet inconnu.")
            return

        # Affichage de l'inventaire
        items = inventory_db.get_inventory(user_id)
        eq = equipement_db.get_equipement(user_id)
        embed = discord.Embed(title=f"Inventaire de {ctx.author.display_name}", color=discord.Color.blurple())
        embed.add_field(
            name="Équipement",
            value=f"Arme : {CATALOGUE_ARMES.get(eq['weapon_id'], {}).get('nom', '???')}\n"
                  f"Armure : {CATALOGUE_ARMURES.get(eq['armor_id'], {}).get('nom', '???')}",
            inline=False,
        )
        if items:
            texte = "\n".join(f"{it['name']} x{it['quantity']}" for it in items)
        else:
            texte = "Vide"
        embed.add_field(name="Objets", value=texte, inline=False)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Shop
    # ------------------------------------------------------------------ #

    @commands.command(name="shop")
    async def shop(self, ctx):
        embed = discord.Embed(title="🛒 Boutique", color=discord.Color.gold())
        armes_txt = "\n".join(f"`{a['id']}` — {a['nom']} ({a['prix']}💰)" for a in CATALOGUE_ARMES.values() if a["prix"] > 0)
        armures_txt = "\n".join(f"`{a['id']}` — {a['nom']} ({a['prix']}💰)" for a in CATALOGUE_ARMURES.values() if a["prix"] > 0)
        potions_txt = "\n".join(f"`{p_id}` — {p['nom']} ({p['prix']}💰)" for p_id, p in CATALOGUE_POTIONS.items())
        embed.add_field(name="Armes", value=armes_txt or "—", inline=False)
        embed.add_field(name="Armures", value=armures_txt or "—", inline=False)
        embed.add_field(name="Potions", value=potions_txt or "—", inline=False)
        embed.set_footer(text="Achetez avec !acheter <id>")
        await ctx.send(embed=embed)

    @commands.command(name="acheter")
    async def acheter(self, ctx, item_id: str):
        user_id = str(ctx.author.id)

        if item_id in CATALOGUE_ARMES:
            prix = CATALOGUE_ARMES[item_id]["prix"]
            nom = CATALOGUE_ARMES[item_id]["nom"]
        elif item_id in CATALOGUE_ARMURES:
            prix = CATALOGUE_ARMURES[item_id]["prix"]
            nom = CATALOGUE_ARMURES[item_id]["nom"]
        elif item_id in CATALOGUE_POTIONS:
            prix = CATALOGUE_POTIONS[item_id]["prix"]
            nom = CATALOGUE_POTIONS[item_id]["nom"]
        else:
            await ctx.send("Objet introuvable dans la boutique.")
            return

        if not economie_db.remove_argent(user_id, prix):
            await ctx.send(f"<@{user_id}> n'a pas assez d'argent ({economie_db.get_argent(user_id)}💰).")
            return

        inventory_db.add_item(user_id, item_id, quantity=1, price=prix)
        await ctx.send(f"<@{user_id}> achète **{nom}** pour {prix}💰.")

    # ------------------------------------------------------------------ #
    # Création d'équipement
    # ------------------------------------------------------------------ #

    @commands.command(name="creation")
    async def creation(self, ctx, type_equipement: str, materiau: str):
        """
        Crée un équipement à partir d'un matériau de loot.
        Exemple : !creation arme ecaille_ignee
        """
        user_id = str(ctx.author.id)

        recettes_armes = {
            "griffe_gobelin": "epee_fer",
            "crocs_salamandre": "lame_flamme",
            "eclat_de_pierre": "marteau_terre",
        }
        recettes_armures = {
            "peau_gobelin": "armure_cuir",
            "ecaille_ignee": "armure_magma",
            "noyau_tellurique": "armure_roche",
        }

        recettes = recettes_armes if type_equipement == "arme" else recettes_armures if type_equipement == "armure" else None
        if recettes is None:
            await ctx.send("Type invalide, utilisez `arme` ou `armure`.")
            return

        if materiau not in recettes:
            await ctx.send("Aucune recette ne correspond à ce matériau.")
            return

        nouvelle_qte, _ = inventory_db.use_item(user_id, materiau, quantity=1)
        if nouvelle_qte is None:
            await ctx.send(f"Vous n'avez pas de **{materiau}**.")
            return

        resultat_id = recettes[materiau]
        inventory_db.add_item(user_id, resultat_id, quantity=1)
        nom = CATALOGUE_ARMES.get(resultat_id) or CATALOGUE_ARMURES.get(resultat_id)
        await ctx.send(f"<@{user_id}> a fabriqué **{nom['nom']}** !")

    # ------------------------------------------------------------------ #
    # Commande admin
    # ------------------------------------------------------------------ #

    def _est_admin(self, user_id):
        return bool(ADMIN_ID) and str(user_id) == ADMIN_ID

    @commands.command(name="spawn_admin")
    async def spawn_admin(self, ctx, monstre_id: str = None):
        """
        Force l'apparition d'un monstre sur ce serveur (réservé à l'ADMIN_ID défini
        dans le .env). Sans argument, un monstre aléatoire apparaît. Avec un id
        (ex: !spawn_admin golem_de_pierre), c'est ce monstre précis qui apparaît.
        """
        await ctx.message.delete()

        if not self._est_admin(ctx.author.id):
            m = await ctx.send("⛔ Commande réservée à l'administrateur.")
            await asyncio.sleep(5)
            await m.delete()
            return

        monstre_data = None
        if monstre_id:
            monstre_data = next(
                (m for m in combat_manager.MONSTRES_DATA if m["id"] == monstre_id), None
            )
            if monstre_data is None:
                await ctx.send(f"Aucun monstre avec l'id `{monstre_id}`.")
                return

        etat = self._etat(ctx.guild.id)
        channel = etat.channel_attente or ctx.channel

        lance = self.spawner_via_admin(ctx.guild, channel, monstre_data)
        if not lance:
            await ctx.send("Un monstre ou un combat est déjà en cours sur ce serveur.")

    def spawner_via_admin(self, guild, channel, monstre_data=None):
        """
        Petite enveloppe autour de `spawner_monstre` (la fonction réutilisable) :
        lance le spawn en tâche de fond, sans bloquer la commande qui l'a déclenché.
        Retourne False immédiatement si un monstre/combat est déjà en cours.
        """
        etat = self._etat(guild.id)
        if etat.monstre_en_attente is not None or (etat.session and not etat.session.termine):
            return False
        asyncio.create_task(self.spawner_monstre(guild, channel, monstre_data))
        return True


async def setup(bot):
    await bot.add_cog(MonsterHunter(bot))