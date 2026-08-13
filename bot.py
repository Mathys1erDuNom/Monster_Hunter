# bot.py
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

from monster_hunter import MonsterHunter

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Nom du salon textuel où les annonces de chasse et les combats se déroulent.
SALON_CHASSE = "chasse"

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
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=SALON_CHASSE)
        if channel is None:
            print(f"⚠️ Aucun salon '{SALON_CHASSE}' trouvé sur {guild.name}, boucle de chasse non démarrée.")
            continue
        cog.demarrer_boucle_spawn(guild, channel)


if __name__ == "__main__":
    bot.run(TOKEN)
