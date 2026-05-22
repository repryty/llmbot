import json
import time
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands

from bot.core.session_manager import session_manager
from bot.core.ollama_client import ollama_client
from bot.core.config import settings

STREAM_UPDATE_INTERVAL = 3.0


def _check_whitelist(interaction: discord.Interaction):
    if interaction.user.id not in settings.whitelist_ids:
        raise app_commands.CheckFailure("이 명령어를 사용할 권한이 없습니다.")


def _thinking_display(thinking_text: str) -> str:
    """Return the last completed line from thinking text, formatted with -# prefix."""
    lines = thinking_text.split("\n")
    # lines[:-1] are lines that ended with \n (completed lines)
    completed = [l.strip() for l in lines[:-1] if l.strip()]
    if completed:
        return f"-# {completed[-1][:200]}"
    # No completed line yet — show tail of current in-progress line
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


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

        session_manager.add_message(user_id, "user", prompt)
        messages = session_manager.get_messages(user_id)
        params = session_manager.get_params(user_id)

        if temperature is not None:
            params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        thinking_parts: list[str] = []
        content_parts: list[str] = []
        is_thinking = False
        last_update = time.monotonic()
        followup_msg = None

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
                    if followup_msg is None:
                        followup_msg = await interaction.followup.send(display)
                    else:
                        await followup_msg.edit(content=display)
                    last_update = now

            full_reply = "".join(content_parts)
            session_manager.add_message(user_id, "assistant", full_reply)

            final = full_reply or "".join(thinking_parts) or "(응답 없음)"
            if len(final) > 2000:
                final = final[:1997] + "..."

            if followup_msg is None:
                await interaction.followup.send(final)
            else:
                await followup_msg.edit(content=final)

        except Exception as e:
            if followup_msg is None:
                await interaction.followup.send(f"에러 발생: {e}", ephemeral=True)
            else:
                await followup_msg.edit(content=f"에러 발생: {e}")

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
            content = msg["content"]
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"**{i}. [{msg['role']}]** {content}")

        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n... (중략)"
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="params", description="현재 세션의 파라미터를 확인합니다.")
    async def params(self, interaction: discord.Interaction):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        params = session_manager.get_params(user_id)
        if not params:
            await interaction.response.send_message("설정된 파라미터가 없습니다.", ephemeral=True)
            return
        lines = [f"**{k}:** {v}" for k, v in params.items()]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # --- 개별 파라미터 설정 명령어 ---

    @app_commands.command(name="set_model", description="Ollama 모델을 변경합니다.")
    @app_commands.describe(model="모델 ID")
    async def set_model(self, interaction: discord.Interaction, model: str):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, model=model)
        await interaction.response.send_message(f"모델이 `{model}`로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_temperature", description="temperature를 설정합니다.")
    @app_commands.describe(value="0~2 사이 값")
    async def set_temperature(self, interaction: discord.Interaction, value: float):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, temperature=value)
        await interaction.response.send_message(f"temperature={value}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_top_p", description="top_p를 설정합니다.")
    @app_commands.describe(value="0~1 사이 값")
    async def set_top_p(self, interaction: discord.Interaction, value: float):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, top_p=value)
        await interaction.response.send_message(f"top_p={value}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_max_tokens", description="max_tokens를 설정합니다.")
    @app_commands.describe(value="최대 토큰 수")
    async def set_max_tokens(self, interaction: discord.Interaction, value: int):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, max_tokens=value)
        await interaction.response.send_message(f"max_tokens={value}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_stop", description="stop 시퀀스를 설정합니다. 쉼표로 여러 개 구분 가능.")
    @app_commands.describe(stop="예: </s>,###")
    async def set_stop(self, interaction: discord.Interaction, stop: str):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        stops = [s.strip() for s in stop.split(",")]
        session_manager.update_params(user_id, stop=stops)
        await interaction.response.send_message(f"stop={stops}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_seed", description="seed를 설정합니다.")
    @app_commands.describe(value="정수 seed 값")
    async def set_seed(self, interaction: discord.Interaction, value: int):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, seed=value)
        await interaction.response.send_message(f"seed={value}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_presence_penalty", description="presence_penalty를 설정합니다.")
    @app_commands.describe(value="-2~2 사이 값")
    async def set_presence_penalty(self, interaction: discord.Interaction, value: float):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, presence_penalty=value)
        await interaction.response.send_message(f"presence_penalty={value}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_frequency_penalty", description="frequency_penalty를 설정합니다.")
    @app_commands.describe(value="-2~2 사이 값")
    async def set_frequency_penalty(self, interaction: discord.Interaction, value: float):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, frequency_penalty=value)
        await interaction.response.send_message(f"frequency_penalty={value}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_n", description="n (생성할 응답 수)를 설정합니다.")
    @app_commands.describe(value="1 이상 정수")
    async def set_n(self, interaction: discord.Interaction, value: int):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, n=value)
        await interaction.response.send_message(f"n={value}로 설정되었습니다.", ephemeral=True)

    @app_commands.command(name="set_response_format", description="response_format을 설정합니다.")
    @app_commands.describe(type_="text 또는 json_object")
    @app_commands.choices(type_=[
        app_commands.Choice(name="text", value="text"),
        app_commands.Choice(name="json_object", value="json_object"),
    ])
    async def set_response_format(self, interaction: discord.Interaction, type_: str):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.update_params(user_id, response_format={"type": type_})
        await interaction.response.send_message(f"response_format={type_}로 설정되었습니다.", ephemeral=True)

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

    @app_commands.command(name="models", description="사용 가능한 Ollama 모델 목록을 조회합니다.")
    async def models(self, interaction: discord.Interaction):
        _check_whitelist(interaction)
        await interaction.response.defer(thinking=True)
        try:
            models = await ollama_client.list_models()
            if not models:
                await interaction.followup.send("모델 목록을 가져올 수 없습니다.")
                return
            lines = [f"- `{m['id']}`" for m in models]
            text = "사용 가능한 모델:\n" + "\n".join(lines)
            if len(text) > 1900:
                text = text[:1900] + "\n... (중략)"
            await interaction.followup.send(text)
        except Exception as e:
            await interaction.followup.send(f"에러 발생: {e}", ephemeral=True)

    # --- 파라미터 제거 / 초기화 ---

    @app_commands.command(name="clear_params", description="현재 세션의 모든 파라미터를 초기화합니다.")
    async def clear_params(self, interaction: discord.Interaction):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.clear_params(user_id)
        await interaction.response.send_message("모든 파라미터가 초기화되었습니다.", ephemeral=True)

    @app_commands.command(name="remove_param", description="특정 파라미터를 제거합니다.")
    @app_commands.describe(key="제거할 파라미터 이름")
    async def remove_param(self, interaction: discord.Interaction, key: str):
        _check_whitelist(interaction)
        user_id = str(interaction.user.id)
        session_manager.remove_param(user_id, key)
        await interaction.response.send_message(f"파라미터 `{key}`가 제거되었습니다.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatCog(bot))
