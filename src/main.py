from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from src.admin_metrics import register_metrics_commands
from src.daily_view import DailyPanelView, register_commands
from src.db import close_db, connect_db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cafedaily")


def _read_discord_token() -> str | None:
    raw = os.environ.get("DISCORD_TOKEN")
    if not raw:
        return None
    token = raw.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1].strip()
    return token or None


class CafeDailyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self) -> None:
        await connect_db()
        self.add_view(DailyPanelView())
        register_commands(self)
        register_metrics_commands(self)

        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()

        logger.info("Slash commands sincronizados: %s", [getattr(c, "name", c) for c in synced])

    async def close(self) -> None:
        await close_db()
        await super().close()


def main() -> None:
    if os.environ.get("HUB_API_URL"):
        from src.hub_main import run_hub_bot
        asyncio.run(run_hub_bot())
        return

    token = _read_discord_token()
    if not token:
        logger.error("Defina DISCORD_TOKEN no ambiente ou no arquivo .env")
        sys.exit(1)

    bot = CafeDailyBot()

    @bot.event
    async def on_ready() -> None:
        logger.info("Conectado como %s (%s)", bot.user, bot.user.id if bot.user else "?")

    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        logger.exception("Token do Discord inválido.")
        sys.exit(1)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
