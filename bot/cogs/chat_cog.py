import json
import logging
import time
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands

from bot.core.session_manager import session_manager
from bot.core.ollama_client import ollama_client
from bot.core.config import settings
from bot.core.error_utils import format_error

logger = logging.getLogger(__name__)

STREAM_UPDATE_INTERVAL = 3.0

CHAT_PARAM_KEYS = [
    "model", "temperature", "top_p", "max_tokens", "stop",
    "seed", "presence_penalty", "frequency_penalty", "n", "response_format",
]

CHAT_PARAM_TYPES = {
    "model": "str",
    "temperature": "float",
    "top_p": "float",
    "max_tokens": "int",
    "stop": "comma_list",
    "seed": "int",
    "presence_penalty": "float",
    "frequency_penalty": "float",
    "n": "int",
    "response_format": "response_format",
}

CHAT_PARAM_VALUE_HINTS = {
    "temperature": "0~2",
    "top_p": "0~1",
    "presence_penalty": "-2~2",
    "frequency_penalty": "-2~2",
    "n": "1 이상",
    "response_format": "text / json_object",
    "stop": "쉼표로 구분 (예: </s>,###)",
}


def _check_whitelist(interaction: discord.Interaction):
    if interaction.user.id not in settings.whitelist_ids:
        raise app_commands.CheckFailure("이 명령어를 사용할 권한이 없습니다.")


def _thinking_display(thinking_text: str) -> str:
    # 남아있는 think 태그 정리
    thinking_text = thinking_text.replace("<think>", "").replace("</think>", "")
    lines = thinking_text.split("\n")
    completed = [l.strip() for l in lines[:-1] if l.strip()]
    if completed:
        return f"-# {completed[-1][:200]}"
    current = lines[-1].strip()
    return f"-# {current[-80:]}" if current else "-# ..."


def _build_stream_display(
    thinking_parts: list[str],
    content_parts: list[str],
    is_thinking: bool,
) -> str:
    if is_thinking:
        return _thinking_display("".join(thinking_parts))
    text = "".join(content_parts)
    return (text[:1990] + "...") if len(text) > 1990 else (text or "...")


async def chat_key_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    choices = ["clear"] + CHAT_PARAM_KEYS
    return [
        app_commands.Choice(name=k, value=k)
        for k in choices
        if current.lower() in k.lower()
    ][:25]


async def chat_value_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    key = interaction.namespace.key or ""
    enum_choices = {
        "response_format": ["text", "json_object"],
    }.get(key, [])
    suggestions = enum_choices + ["clear"]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions
        if current.lower() in s.lower()
    ][:25]


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _stream_chat(
        self,
        user_id: str,
        prompt: str,
        params: dict,
        send_fn,
        edit_fn,
        error_fn,
    ):
        session_manager.add_message(user_id, "user", prompt)
        messages = session_manager.get_messages(user_id)

        thinking_parts: list[str] = []
        content_parts: list[str] = []
        is_thinking = False
        last_update = time.monotonic()
        reply_msg = None

        try:
            async for thinking_chunk, content_chunk in ollama_client.chat_stream(
                messages=messages, **params
            ):
                if thinking_chunk:
                    thinking_parts.append(thinking_chunk)
                    is_thinking = True
                if content_chunk:
                    content_parts.append(content_chunk)
                    is_thinking = False

                now = time.monotonic()
                if now - last_update >= STREAM_UPDATE_INTERVAL:
                    display = _build_stream_display(thinking_parts, content_parts, is_thinking)
                    if reply_msg is None:
                        reply_msg = await send_fn(display)
                    else:
                        await edit_fn(reply_msg, display)
                    last_update = now

            full_reply = "".join(content_parts)
            session_manager.add_message(user_id, "assistant", full_reply)

            final = full_reply or "".join(thinking_parts) or "(응답 없음)"
            if len(final) > 2000:
                final = final[:1997] + "..."

            if reply_msg is None:
                await send_fn(final)
            else:
                await edit_fn(reply_msg, final)

        except Exception as e:
            logger.exception(
                "chat 오류 | user=%s prompt=%r params=%r messages_count=%d",
                user_id, prompt, params, len(messages),
            )
            error_text = format_error(
                e,
                user=user_id,
                prompt=prompt,
                params=params,
                messages_count=len(messages),
            )
            await error_fn(reply_msg, error_text)

    @app_commands.command(name="chat", description="Ollama AI와 대화를 나눕니다.")
    @app_commands.describe(
        prompt="보낼 메시지",
        temperature="temperature (0~2)",
        top_p="top_p (0~1)",
        max_tokens="최대 토큰 수",
        system="이번 메시지에만 적용할 시스템 프롬프트 (선택)",
    )
    async def chat(
        self,
        interaction: discord.Interaction,
        prompt: str,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
    ):
        _check_whitelist(interaction)
        await interaction.response.defer(thinking=True)
        user_id = str(interaction.user.id)

        if system:
            session_manager.set_system_prompt(user_id, system)

        params = session_manager.get_params(user_id)
        if temperature is not None:
            params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        async def send_fn(text):
            return await interaction.followup.send(text)

        async def edit_fn(msg, text):
            await msg.edit(content=text)

        async def error_fn(msg, text):
            if msg is None:
                await interaction.followup.send(text, ephemeral=True)
            else:
                await msg.edit(content=text)

        await self._stream_chat(user_id, prompt, params, send_fn, edit_fn, error_fn)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.bot.user not in message.mentions:
            return
        if message.author.id not in settings.whitelist_ids:
            return

        content = (
            message.content
            .replace(f"<@{self.bot.user.id}>", "")
            .replace(f"<@!{self.bot.user.id}>", "")
            .strip()
        )
        if not content:
            return

        user_id = str(message.author.id)
        params = session_manager.get_params(user_id)

        async def send_fn(text):
            return await message.reply(text)

        async def edit_fn(msg, text):
            await msg.edit(content=text)

        async def error_fn(msg, text):
            if msg is None:
                await message.reply(text)
            else:
                await msg.edit(content=text)

        async with message.channel.typing():
            await self._stream_chat(user_id, content, params, send_fn, edit_fn, error_fn)

    @app_commands.command(name="reset", description="대화 세션을 초기화합니다.")
    async def reset(self, interaction: discord.Interaction):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.reset(user_id)
        await interaction.response.send_message("세션이 초기화되었습니다.", ephemeral=True)

    @app_commands.command(name="system", description="시스템 프롬프트를 설정합니다.")
    @app_commands.describe(prompt="시스템 프롬프트 내용")
    async def system(self, interaction: discord.Interaction, prompt: str):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.set_system_prompt(user_id, prompt)
        await interaction.response.send_message("시스템 프롬프트가 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="add", description="대화 기록에 임의 메시지를 추가합니다.")
    @app_commands.describe(role="역할 (system/user/assistant)", content="메시지 내용")
    async def add(
        self,
        interaction: discord.Interaction,
        role: str,
        content: str,
    ):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        if role not in ("system", "user", "assistant"):
            await interaction.response.send_message("role은 system/user/assistant 중 하나여야 합니다.", ephemeral=True)
            return
        session_manager.add_message(user_id, role, content)
        await interaction.response.send_message(f"{role} 메시지를 추가했습니다.", ephemeral=True)

    @app_commands.command(name="delete", description="대화 기록에서 특정 메시지를 삭제합니다.")
    @app_commands.describe(index="삭제할 메시지 번호 (1부터 시작)")
    async def delete(self, interaction: discord.Interaction, index: int):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        success = session_manager.delete_message(user_id, index)
        if success:
            await interaction.response.send_message(f"{index}번 메시지를 삭제했습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("유효하지 않은 인덱스입니다.", ephemeral=True)

    @app_commands.command(name="history", description="현재 세션의 대화 기록을 확인합니다.")
    async def history(self, interaction: discord.Interaction):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        messages = session_manager.get_messages(user_id)
        if not messages:
            await interaction.response.send_message("대화 기록이 비어 있습니다.", ephemeral=True)
            return

        lines = []
        for i, msg in enumerate(messages, 1):
            c = msg["content"]
            if len(c) > 200:
                c = c[:200] + "..."
            lines.append(f"**{i}. [{msg['role']}]** {c}")

        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n... (중략)"
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="models", description="사용 가능한 Ollama 모델 목록을 조회합니다.")
    async def models(self, interaction: discord.Interaction):
        _check_whitelist(interaction)
        await interaction.response.defer(thinking=True)
        try:
            model_list = await ollama_client.list_models()
            if not model_list:
                await interaction.followup.send("모델 목록을 가져올 수 없습니다.")
                return
            lines = [f"- `{m['id']}`" for m in model_list]
            text = "사용 가능한 모델:\n" + "\n".join(lines)
            if len(text) > 1900:
                text = text[:1900] + "\n... (중략)"
            await interaction.followup.send(text)
        except Exception as e:
            logger.exception("models 명령어 오류 | user=%s", interaction.user.id)
            await interaction.followup.send(format_error(e, command="models"), ephemeral=True)

    @app_commands.command(name="tools", description="tools 설정 (JSON 문자열). 비워두면 제거.")
    @app_commands.describe(json_str="JSON 문자열 또는 비워두기")
    async def tools(self, interaction: discord.Interaction, json_str: Optional[str] = None):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        if json_str is None or json_str.strip() == "":
            session_manager.remove_param(user_id, "tools")
            await interaction.response.send_message("tools 설정이 제거되었습니다.", ephemeral=True)
            return
        try:
            parsed = json.loads(json_str)
            session_manager.update_params(user_id, tools=parsed)
            await interaction.response.send_message("tools 설정이 적용되었습니다.", ephemeral=True)
        except json.JSONDecodeError:
            await interaction.response.send_message("유효하지 않은 JSON입니다.", ephemeral=True)

    @app_commands.command(name="set", description="파라미터를 설정·조회·초기화합니다.")
    @app_commands.describe(
        key="파라미터 이름 (생략 시 전체 보기, 'clear'로 전체 초기화)",
        value="설정할 값 (생략 시 현재 값 조회, 'clear'로 해당 파라미터 제거)",
    )
    @app_commands.autocomplete(key=chat_key_autocomplete, value=chat_value_autocomplete)
    async def set_param(
        self,
        interaction: discord.Interaction,
        key: Optional[str] = None,
        value: Optional[str] = None,
    ):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)

        if key is None:
            current = session_manager.get_params(user_id)
            if not current:
                await interaction.response.send_message("설정된 파라미터가 없습니다.", ephemeral=True)
                return
            lines = [f"**{k}:** `{v}`" for k, v in current.items()]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        if key == "clear":
            session_manager.clear_params(user_id)
            await interaction.response.send_message("모든 파라미터가 초기화되었습니다.", ephemeral=True)
            return

        if key not in CHAT_PARAM_TYPES:
            valid = ", ".join(f"`{k}`" for k in CHAT_PARAM_KEYS)
            await interaction.response.send_message(
                f"알 수 없는 파라미터: `{key}`\n유효한 파라미터: {valid}", ephemeral=True
            )
            return

        if value is None:
            current = session_manager.get_params(user_id)
            hint = CHAT_PARAM_VALUE_HINTS.get(key, "")
            hint_str = f"  ({hint})" if hint else ""
            if key in current:
                await interaction.response.send_message(
                    f"**{key}:** `{current[key]}`{hint_str}", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"**{key}:** 설정되지 않음{hint_str}", ephemeral=True
                )
            return

        if value == "clear":
            session_manager.remove_param(user_id, key)
            await interaction.response.send_message(f"파라미터 `{key}`가 제거되었습니다.", ephemeral=True)
            return

        type_name = CHAT_PARAM_TYPES[key]
        try:
            if type_name == "str":
                parsed = value
            elif type_name == "int":
                parsed = int(value)
            elif type_name == "float":
                parsed = float(value)
            elif type_name == "comma_list":
                parsed = [s.strip() for s in value.split(",") if s.strip()]
            elif type_name == "response_format":
                if value not in ("text", "json_object"):
                    raise ValueError("text 또는 json_object 중 하나여야 합니다")
                parsed = {"type": value}
            else:
                parsed = value
        except ValueError as e:
            hint = CHAT_PARAM_VALUE_HINTS.get(key, "")
            hint_str = f"\n예상 형식: {hint}" if hint else ""
            await interaction.response.send_message(
                f"잘못된 값: `{value}`{hint_str}\n오류: {e}", ephemeral=True
            )
            return

        session_manager.update_params(user_id, **{key: parsed})
        await interaction.response.send_message(f"`{key}` = `{parsed}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatCog(bot))
