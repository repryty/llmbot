import traceback
import discord
from discord.ext import commands
from discord import app_commands

from bot.core.config import settings
from bot.core.logging_config import LOG_FILE

DISCORD_MESSAGE_LIMIT = 2000
LOG_CHUNK_LIMIT = DISCORD_MESSAGE_LIMIT - 200
MAX_LOG_LINES = 1000


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _check_whitelist(self, interaction: discord.Interaction) -> None:
        if interaction.user.id not in settings.whitelist_ids:
            raise app_commands.CheckFailure("이 명령어를 사용할 권한이 없습니다.")

    def _tail_log_lines(self, line_count: int) -> list[str]:
        if line_count <= 0:
            return []
        with LOG_FILE.open("rb") as log_file:
            log_file.seek(0, 2)
            position = log_file.tell()
            buffer = bytearray()
            chunk_size = 1024
            newline_count = 0
            while position > 0 and newline_count <= line_count:
                read_size = min(chunk_size, position)
                position -= read_size
                log_file.seek(position)
                chunk = log_file.read(read_size)
                buffer[:0] = chunk
                newline_count += chunk.count(b"\n")
                if position == 0:
                    break
        text = buffer.decode("utf-8", errors="replace")
        return text.splitlines()[-line_count:]

    async def _send_log_lines(self, interaction: discord.Interaction, lines: list[str]) -> None:
        chunks: list[str] = []
        current = ""
        limit = LOG_CHUNK_LIMIT
        for line in lines:
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
        if lines <= 0:
            await interaction.response.send_message("줄 수는 1 이상이어야 합니다.", ephemeral=True)
            return
        notice = None
        if lines > MAX_LOG_LINES:
            notice = f"[notice] 요청한 줄 수가 최대치({MAX_LOG_LINES})로 제한되었습니다."
        safe_lines = min(lines, MAX_LOG_LINES)
        if not LOG_FILE.exists():
            await interaction.response.send_message("로그 파일이 없습니다.", ephemeral=True)
            return
        try:
            recent_lines = self._tail_log_lines(safe_lines)
        except Exception as e:
            await interaction.response.send_message(f"로그 읽기 실패: {e}", ephemeral=True)
            return
        if not recent_lines:
            await interaction.response.send_message("로그가 비어 있습니다.", ephemeral=True)
            return
        if notice:
            recent_lines.insert(0, notice)
        await self._send_log_lines(interaction, recent_lines)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
