# combat_manager.py
import asyncio
import json
import os
import random
import time

import stats_db
import equipement_db
import economie_db
import inventory_db
import combat_utils

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, "monstres.json"), encoding="utf-8") as f:
    MONSTRES_DATA = json.load(f)

# --- Réglages temporels (en secondes) ---
INTERVALLE_SPAWN = 30 * 60        # un monstre apparait toutes les 30 min
DELAI_APRES_COMBAT = 30           # 30s après une mort avant que le minuteur de spawn ne redémarre
TIMEOUT_CHASSE = 20 * 60          # le monstre s'en va si personne ne le chasse en 20 min
INTERVALLE_ATTAQUE_JOUEUR = 5     # un joueur en !attaque tape toutes les 5s
DELAI_PREVENANCE_ATTAQUE = 5      # le monstre prévient 5s avant d'attaquer


def monstre_aleatoire():
    return random.choice(MONSTRES_DATA)


class MonstreCombat:
    """Représente l'état courant du monstre pendant un combat."""

    def __init__(self, data):
        self.data = data
        self.id = data["id"]
        self.nom = data["nom"]
        self.hp_max = data["hp"]
        self.hp = data["hp"]
        self.attaque = data["attaque"]
        self.defense_base = data["defense"]
        self.defense = data["defense"]
        self.element = data["element"]
        self.image = data["image"]
        self.intervalle_attaque = data["intervalle_attaque"]
        self.attaques = data["attaques"]

    @property
    def est_mort(self):
        return self.hp <= 0

    def subir_degats(self, montant):
        self.hp = max(self.hp - montant, 0)
        return self.hp

    def choisir_attaque(self):
        return random.choice(self.attaques)

    def appliquer_effet(self, attaque):
        """Applique un bonus/malus du monstre déclenché par son attaque (simplifié : instantané)."""
        bonus = attaque.get("bonus")
        if bonus and bonus.get("stat") == "attaque":
            self.attaque += bonus["valeur"]
        if bonus and bonus.get("stat") == "defense":
            self.defense += bonus["valeur"]


class CombatSession:
    """
    Représente une chasse en cours sur un serveur : le monstre commun à tous
    les joueurs, les participants, leurs états (attaque/esquive/soin) et les
    dégâts infligés par chacun.
    """

    def __init__(self, guild_id, channel, monstre_data):
        self.guild_id = guild_id
        self.channel = channel  # salon textuel où le combat se déroule
        self.monstre = MonstreCombat(monstre_data)

        self.demarre = False          # True dès qu'un joueur a fait !chasse
        self.termine = False
        self.participants = set()     # user_ids ayant rejoint via !chasse
        self.etats = {}               # user_id -> "attaque" | "esquive" | "soin"
        self.esquive_active = {}      # user_id -> bool, mis à jour juste avant l'attaque du monstre
        self.degats_infliges = {}     # user_id -> total dégâts sur ce monstre
        self.messages_a_supprimer = []  # messages à nettoyer en fin de combat

        self._tache_attaques_joueurs = None
        self._tache_attaques_monstre = None
        self._tache_timeout = None

    # ------------------------------------------------------------------ #
    # Gestion des participants
    # ------------------------------------------------------------------ #

    def rejoindre(self, user_id):
        user_id = str(user_id)
        stats_db.create_player(user_id)
        self.participants.add(user_id)
        self.etats.setdefault(user_id, "attaque")
        self.degats_infliges.setdefault(user_id, 0)

    def joueurs_vivants(self):
        return [uid for uid in self.participants if not stats_db.is_dead(uid)]

    def tous_morts(self):
        return len(self.joueurs_vivants()) == 0

    def definir_etat(self, user_id, etat):
        """etat: 'attaque', 'esquive' ou 'soin'."""
        user_id = str(user_id)
        if user_id not in self.participants:
            return False
        if stats_db.is_dead(user_id):
            return False
        self.etats[user_id] = etat
        return True

    # ------------------------------------------------------------------ #
    # Boucle des attaques des joueurs (toutes les 5s, dégats au monstre)
    # ------------------------------------------------------------------ #

    async def _boucle_attaques_joueurs(self):
        try:
            while not self.termine:
                await asyncio.sleep(INTERVALLE_ATTAQUE_JOUEUR)
                if self.termine:
                    break
                for uid in list(self.participants):
                    if stats_db.is_dead(uid):
                        continue
                    if self.etats.get(uid) != "attaque":
                        continue
                    stats = stats_db.get_stats(uid)
                    bonus = equipement_db.get_bonus_combat(uid)
                    degat = combat_utils.degat_infliges_au_monstre(
                        attaque_perso=stats["attaque"],
                        degat_arme=bonus["degat_arme"],
                        element_arme=bonus["element_arme"],
                        element_monstre=self.monstre.element,
                        defense_monstre=self.monstre.defense,
                    )
                    self.monstre.subir_degats(degat)
                    self.degats_infliges[uid] = self.degats_infliges.get(uid, 0) + degat

                    msg = await self.channel.send(
                        f"<@{uid}> inflige **{degat}** dégâts à {self.monstre.nom} "
                        f"({self.monstre.hp}/{self.monstre.hp_max} HP)"
                    )
                    self.messages_a_supprimer.append(msg)

                    if self.monstre.est_mort:
                        await self._fin_combat(victoire=True)
                        return
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------ #
    # Boucle des attaques du monstre (avec prévenance de 5s avant impact)
    # ------------------------------------------------------------------ #

    async def _boucle_attaques_monstre(self):
        try:
            while not self.termine:
                await asyncio.sleep(self.monstre.intervalle_attaque)
                if self.termine or self.monstre.est_mort:
                    break

                attaque = self.monstre.choisir_attaque()
                msg = await self.channel.send(
                    f"⚠️ {self.monstre.nom} prépare **{attaque['nom']}** ! "
                    f"Faites `!esquive` dans les {DELAI_PREVENANCE_ATTAQUE}s pour éviter les dégâts !"
                )
                self.messages_a_supprimer.append(msg)

                # snapshot de qui est en esquive AU MOMENT DE L'ANNONCE, puis on
                # laisse le délai de prévenance s'écouler pour que les joueurs réagissent
                await asyncio.sleep(DELAI_PREVENANCE_ATTAQUE)
                if self.termine:
                    break

                self.monstre.appliquer_effet(attaque)

                for uid in self.joueurs_vivants():
                    if self.etats.get(uid) == "esquive":
                        continue  # esquive réussie, pas de dégâts

                    stats = stats_db.get_stats(uid)
                    bonus = equipement_db.get_bonus_combat(uid)
                    degat = combat_utils.degat_recus_par_joueur(
                        attaque_monstre=self.monstre.attaque,
                        element_attaque_monstre=attaque["element"],
                        degat_base_attaque=attaque["degat_base"],
                        element_armure=bonus["element_armure"],
                        defense_joueur=stats["defense"] + bonus["defense_armure"],
                    )
                    nouveau_hp, mort = stats_db.damage(uid, degat)

                    if mort:
                        txt = f"💀 <@{uid}> a été vaincu par {self.monstre.nom} !"
                    else:
                        txt = f"<@{uid}> subit **{degat}** dégâts ({nouveau_hp}/{stats['hp_max']} HP)"
                    m = await self.channel.send(txt)
                    self.messages_a_supprimer.append(m)

                if self.tous_morts():
                    await self._fin_combat(victoire=False)
                    return
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------ #
    # Cycle de vie du combat
    # ------------------------------------------------------------------ #

    def demarrer(self):
        self.demarre = True
        self._tache_attaques_joueurs = asyncio.create_task(self._boucle_attaques_joueurs())
        self._tache_attaques_monstre = asyncio.create_task(self._boucle_attaques_monstre())

    async def _fin_combat(self, victoire):
        self.termine = True
        for tache in (self._tache_attaques_joueurs, self._tache_attaques_monstre, self._tache_timeout):
            if tache and not tache.done():
                tache.cancel()

        if victoire:
            data = self.monstre.data
            gagnants = self.joueurs_vivants()

            for uid in self.participants:
                if uid not in gagnants:
                    continue  # les morts ne peuvent pas looter
                xp_info = stats_db.add_xp(uid, data["xp_gagne"])
                argent = random.randint(data["argent_min"], data["argent_max"])
                economie_db.add_argent(uid, argent)

            if gagnants:
                meilleur = max(gagnants, key=lambda uid: self.degats_infliges.get(uid, 0))
            else:
                meilleur = None

            resume = "\n".join(
                f"<@{uid}> : {self.degats_infliges.get(uid, 0)} dégâts"
                for uid in sorted(self.participants, key=lambda u: -self.degats_infliges.get(u, 0))
            )
            texte = (
                f"🎉 {self.monstre.nom} a été vaincu !\n\n"
                f"**Dégâts infligés**\n{resume}\n\n"
            )
            if meilleur:
                texte += f"🏆 <@{meilleur}> a fait le plus de dégâts et reçoit un bonus de loot !\n"
            texte += "Les survivants peuvent utiliser `!loot` pour récupérer des ressources."
            await self.channel.send(texte)
        else:
            await self.channel.send(
                f"💀 Tous les joueurs sont morts... {self.monstre.nom} s'enfuit avec ses HP restants."
            )

        # Nettoyage des messages de combat
        for msg in self.messages_a_supprimer:
            try:
                await msg.delete()
            except Exception:
                pass
        self.messages_a_supprimer.clear()

    async def annuler_sans_combat(self):
        """Le monstre s'en va car personne n'est venu le chasser à temps."""
        self.termine = True
        for tache in (self._tache_attaques_joueurs, self._tache_attaques_monstre, self._tache_timeout):
            if tache and not tache.done():
                tache.cancel()
        await self.channel.send(f"{self.monstre.nom} s'est lassé d'attendre et s'en va...")

    def loot(self, user_id):
        """
        Distribue le loot du monstre au joueur (à appeler après la victoire).
        Retourne la liste des items obtenus, ou None si non éligible.
        """
        user_id = str(user_id)
        if not self.termine or self.monstre.hp > 0:
            return None
        if user_id not in self.participants or stats_db.is_dead(user_id):
            return None

        est_meilleur = max(self.participants, key=lambda u: self.degats_infliges.get(u, 0)) == user_id
        items_obtenus = []
        for entree in self.monstre.data["loot"]:
            chance = entree["chance"] * (1.5 if est_meilleur else 1.0)
            if random.random() <= chance:
                inventory_db.add_item(user_id, entree["item"], quantity=1, rarity="materiau")
                items_obtenus.append(entree["item"])
        return items_obtenus
