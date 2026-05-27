import traceback
from pathlib import Path
import discord
from discord.ext import commands
from discord import app_commands

from bot.core.config import settings
from bot.core.logging_config import LOG_FILE


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _check_whitelist(self, interaction: discord.Interaction) -> None:
        if interaction.user.id not in settings.whitelist_ids:
            raise app_commands.CheckFailure("이 명령어를 사용할 권한이 없습니다.")

    async def _send_log_lines(self, interaction: discord.Interaction, lines: list[str]) -> None:
        chunks: list[str] = []
        current = ""
        limit = 1800
        for line in lines:
            line = line.rstrip("\n")
            if not current:
                current = line
                continue
            if len(current) + len(line) + 1 > limit:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}"
        if current:
            chunks.append(current)

        if len(chunks) == 1:
            await interaction.response.send_message(f"```\n{chunks[0]}\n```", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        for chunk in chunks:
            await interaction.followup.send(f"```\n{chunk}\n```", ephemeral=True)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message

        if isinstance(error, app_commands.CheckFailure):
            await send("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
            original = error.original
            await send(f"명령어 실행 중 오류가 발생했습니다: {original}", ephemeral=True)
            traceback.print_exception(type(original), original, original.__traceback__)
        else:
            await send(f"오류가 발생했습니다: {error}", ephemeral=True)
            traceback.print_exception(type(error), error, error.__traceback__)

    @app_commands.command(name="logs", description="최근 로그를 확인합니다.")
    @app_commands.describe(lines="가져올 마지막 줄 수 (기본 200, 최대 1000)")
    async def logs(self, interaction: discord.Interaction, lines: int = 200):
        self._check_whitelist(interaction)
        safe_lines = max(1, min(lines, 1000))
        log_path = Path(LOG_FILE)
        if not log_path.exists():
            await interaction.response.send_message("로그 파일이 없습니다.", ephemeral=True)
            return
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            await interaction.response.send_message(f"로그 읽기 실패: {e}", ephemeral=True)
            return
        if not content.strip():
            await interaction.response.send_message("로그가 비어 있습니다.", ephemeral=True)
            return
        all_lines = content.splitlines()
        recent_lines = all_lines[-safe_lines:]
        await self._send_log_lines(interaction, recent_lines)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
