import asyncio
import logging
import discord
from discord.ext import commands

from bot.core.config import settings
from bot.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "bot.cogs.chat_cog",
    "bot.cogs.novelai_cog",
    "bot.cogs.admin_cog",
]


async def load_extensions():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"Loaded {cog}")
        except Exception:
            logger.exception(f"Failed to load {cog}")


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception:
        logger.exception("Failed to sync commands")


async def main():
    async with bot:
        await load_extensions()
        await bot.start(settings.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
