# bot.py
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

from monster_hunter import MonsterHunter

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ID du salon textuel où les annonces de chasse et les combats se déroulent.
CHASSE_CHANNEL_ID = int(os.getenv("CHASSE_CHANNEL_ID"))

# ID du salon vocal à surveiller pour déclencher le spawn (optionnel).
# Si vide/non défini, le bot surveille TOUS les salons vocaux du serveur.
_vocal_id = os.getenv("CHASSE_VOICE_CHANNEL_ID", "").strip()
CHASSE_VOICE_CHANNEL_ID = int(_vocal_id) if _vocal_id else None

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")
    if "MonsterHunter" not in bot.cogs:
        await bot.add_cog(MonsterHunter(bot))

    cog = bot.get_cog("MonsterHunter")

    channel = bot.get_channel(CHASSE_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ Aucun salon trouvé pour l'ID {CHASSE_CHANNEL_ID}, boucle de chasse non démarrée.")
        return

    cog.demarrer_boucle_spawn(channel.guild, channel, vocal_channel_id=CHASSE_VOICE_CHANNEL_ID)


if __name__ == "__main__":
    bot.run(TOKEN)