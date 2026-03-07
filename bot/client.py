import discord
from discord.ext import commands
import logging
import config

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

def create_bot() -> commands.Bot:
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info("Bot logged in as %s (id=%s)", bot.user, bot.user.id)
        try:
            guild = discord.Object(id=config.DISCORD_GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %d slash commands to guild %d", len(synced), config.DISCORD_GUILD_ID)
        except Exception as e:
            logger.error("Failed to sync commands: %s", e)

    return bot

async def load_cogs(bot: commands.Bot):
    """Load all cogs. Call this before bot.start()."""
    await bot.load_extension("bot.cogs.commands")
    await bot.load_extension("bot.cogs.alerts")
    # Additional cogs loaded here as they are built:
    await bot.load_extension("bot.cogs.recommendations")
