"""로깅 COG — 디스코드에서 로그를 조회하고 디버그 모드를 제어한다.

명령어:
    /logs  [lines]    — 최근 N 줄 로그 조회 (기본 2, 최대 200)
    /log_size         — 로그 파일 크기 / 경로 확인
    /log_debug [mode] — 디버그 모드 조회 / 전환
                        mode: "on" | "off" (생략 시 현재 상태 표시)

모드 설명:
    일반 모드 (기본): Ollama / NovelAI API 호출 로그만 파일에 저장
    디버그 모드      : discord.*, bot.* 포함 모든 로그 파일에 저장
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.bot_logger import (
    get_log_size_info,
    get_recent_logs,
    is_debug_mode,
    set_debug_mode,
)
from bot.core.config import settings

logger = logging.getLogger(__name__)

_MAX_DISCORD_MSG = 1900  # 코드 블록 마커 포함 여유분 고려


def _check_whitelist(interaction: discord.Interaction) -> None:
    if settings.whitelist_ids and interaction.user.id not in settings.whitelist_ids:
        raise app_commands.CheckFailure("이 명령어를 사용할 권한이 없습니다.")


def _split_chunks(text: str, size: int = _MAX_DISCORD_MSG) -> list[str]:
    chunks: list[str] = []
    while text:
        chunks.append(text[:size])
        text = text[size:]
    return chunks or ["(내용 없음)"]


class LoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /logs ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="logs", description="최근 로그를 조회합니다.")
    @app_commands.describe(lines="가져올 줄 수 (기본 2, 최대 200)")
    async def logs(
        self,
        interaction: discord.Interaction,
        lines: int = 2,
    ) -> None:
        _check_whitelist(interaction)

        lines = max(1, min(lines, 200))

        await interaction.response.defer(ephemeral=True)

        content = get_recent_logs(lines)
        chunks = _split_chunks(content)

        mode_tag = "🔍 디버그" if is_debug_mode() else "📡 API전용"
        header = f"📋 **최근 로그 (마지막 {lines}줄)** [{mode_tag}]\n"
        await interaction.followup.send(header + f"```\n{chunks[0]}\n```", ephemeral=True)

        for chunk in chunks[1:]:
            await interaction.followup.send(f"```\n{chunk}\n```", ephemeral=True)

    # ── /log_size ─────────────────────────────────────────────────────────────

    @app_commands.command(name="log_size", description="로그 파일 크기를 확인합니다.")
    async def log_size(self, interaction: discord.Interaction) -> None:
        _check_whitelist(interaction)

        info = get_log_size_info()

        if not info["exists"]:
            await interaction.response.send_message(
                "📋 로그 파일이 아직 없습니다.", ephemeral=True
            )
            return

        bar_filled = int(info["mb"] / info["max_mb"] * 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        msg = (
            f"📋 **로그 파일 상태**\n"
            f"크기: **{info['mb']:.2f} MB** / {info['max_mb']:.0f} MB\n"
            f"`[{bar}]`\n"
            f"경로: `{info['path']}`\n"
            f"5 MB 초과 시 자동 회전 (백업 최대 2개)"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /log_debug ────────────────────────────────────────────────────────────

    @app_commands.command(
        name="log_debug",
        description="로그 디버그 모드를 켜거나 끕니다. 생략 시 현재 상태 표시.",
    )
    @app_commands.describe(mode="on = 전체 로그 저장 / off = API 호출만 저장")
    @app_commands.choices(mode=[
        app_commands.Choice(name="on  — 모든 로그 저장 (discord 포함)", value="on"),
        app_commands.Choice(name="off — API 호출 로그만 저장 (기본)", value="off"),
    ])
    async def log_debug(
        self,
        interaction: discord.Interaction,
        mode: str | None = None,
    ) -> None:
        _check_whitelist(interaction)

        if mode is None:
            # 현재 상태 조회
            cur = is_debug_mode()
            state = "🔍 **디버그 모드 ON** — 모든 로그 저장 중" if cur else "📡 **일반 모드** — API 호출 로그만 저장 중"
            await interaction.response.send_message(state, ephemeral=True)
            return

        enabled = mode == "on"
        set_debug_mode(enabled)

        if enabled:
            msg = "🔍 **디버그 모드 ON** — discord 포함 모든 로그를 파일에 저장합니다."
        else:
            msg = "📡 **일반 모드** — Ollama / NovelAI API 호출 로그만 저장합니다."

        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingCog(bot))
