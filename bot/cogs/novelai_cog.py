import io
import json
import logging
from pathlib import Path
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands, ui

from bot.core.config import settings
from bot.core.novelai_client import novelai_client
from bot.core.error_utils import format_error
from bot.core.appearance_gen import generate_appearance

logger = logging.getLogger(__name__)

PARAMS_PATH = Path("data/image_params.json")


def whitelist_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id in settings.whitelist_ids


IMAGE_PRESETS = {
    "landscape": {
        "model": "nai-diffusion-4-5-full",
        "width": 1216,
        "height": 832,
        "sampler": "k_euler_ancestral",
        "noise_schedule": "karras",
        "steps": 28,
        "scale": 5,
        "cfg_rescale": 0,
    },
    "portrait": {
        "model": "nai-diffusion-4-5-full",
        "width": 832,
        "height": 1216,
        "sampler": "k_euler_ancestral",
        "noise_schedule": "karras",
        "steps": 28,
        "scale": 5,
        "cfg_rescale": 0,
    },
}

# _last_prompt, _last_action : 내부 추적용 (API에 전달하지 않음)
# model                      : API 최상위 필드 (parameters 안에 들어가지 않음)
# _pre_positive, _pre_negative : 선행 프롬프트 (그림체 프리셋 저장용)
# _random_appearance         : 랜덤 외형 태그 (버튼으로 재생성)
_INTERNAL_KEYS = {
    "_last_prompt", "_last_action", "model",
    "_pre_positive", "_pre_negative", "_random_appearance",
}

IMAGE_PARAM_KEYS = [
    "model", "width", "height", "scale", "sampler", "steps", "seed",
    "n_samples", "negative_prompt", "ucPreset", "qualityToggle",
    "noise_schedule", "cfg_rescale", "sm", "sm_dyn", "dynamic_thresholding",
    "strength", "noise",
]

IMAGE_PARAM_TYPES = {
    "model": "str",
    "width": "int",
    "height": "int",
    "scale": "float",
    "sampler": "str",
    "steps": "int",
    "seed": "int",
    "n_samples": "int",
    "negative_prompt": "str",
    "ucPreset": "int",
    "qualityToggle": "bool",
    "noise_schedule": "str",
    "cfg_rescale": "float",
    "sm": "bool",
    "sm_dyn": "bool",
    "dynamic_thresholding": "bool",
    "strength": "float",
    "noise": "float",
}

IMAGE_PARAM_VALUE_HINTS = {
    "scale": "CFG 강도",
    "ucPreset": "0=Heavy / 1=Light / 2=None",
    "sampler": "k_euler_ancestral / k_euler / k_dpm_2 / ...",
    "noise_schedule": "karras / exponential / polyexponential / native",
    "strength": "0~1 (img2img 강도)",
    "seed": "0=랜덤",
    "sm": "SMEA (true/false)",
    "sm_dyn": "SMEA DYN (true/false)",
    "qualityToggle": "품질 태그 자동 추가 (true/false)",
    "dynamic_thresholding": "다이나믹 스레셔홀딩 (true/false)",
}

IMAGE_PARAM_VALUE_CHOICES: dict[str, list[str]] = {
    "model": [
        "nai-diffusion-4-5-full", "nai-diffusion-4-5", "nai-diffusion-4-5-curated",
        "nai-diffusion-4", "nai-diffusion-4-curated-preview", "nai-diffusion-3",
    ],
    "sampler": [
        "k_euler_ancestral", "k_euler", "k_dpm_2", "k_dpm_2_ancestral",
        "k_dpmpp_2s_ancestral", "k_dpmpp_2m", "k_dpmpp_sde", "ddim_v3",
    ],
    "noise_schedule": ["karras", "exponential", "polyexponential", "native"],
    "ucPreset": ["0", "1", "2"],
    "qualityToggle": ["true", "false"],
    "sm": ["true", "false"],
    "sm_dyn": ["true", "false"],
    "dynamic_thresholding": ["true", "false"],
}


async def nai_key_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    choices = ["clear"] + IMAGE_PARAM_KEYS
    return [
        app_commands.Choice(name=k, value=k)
        for k in choices
        if current.lower() in k.lower()
    ][:25]


async def nai_value_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    key = interaction.namespace.key or ""
    enum_choices = IMAGE_PARAM_VALUE_CHOICES.get(key, [])
    suggestions = enum_choices + ["clear"]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions
        if current.lower() in s.lower()
    ][:25]


def _build_prompt_display(
    prompt: str,
    negative: str = "",
    pre_positive: str = "",
    pre_negative: str = "",
    appearance: str = "",
) -> str:
    def trunc(s: str, n: int = 200) -> str:
        return s[:n] + "…" if len(s) > n else s

    lines = []
    if pre_positive:
        lines.append(f"**선행+:** `{trunc(pre_positive)}`")
    if appearance:
        lines.append(f"**외형:** `{trunc(appearance)}`")
    if prompt:
        lines.append(f"**프롬프트:** `{trunc(prompt)}`")
    if pre_negative:
        lines.append(f"**선행-:** `{trunc(pre_negative)}`")
    if negative:
        lines.append(f"**네거티브:** `{trunc(negative)}`")
    return "\n".join(lines)


class NAIPromptModal(ui.Modal, title="프롬프트 수정"):
    pre_positive = ui.TextInput(
        label="선행 포지티브 (pre-prompt)",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )
    prompt = ui.TextInput(
        label="포지티브 프롬프트",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True,
    )
    pre_negative = ui.TextInput(
        label="선행 네거티브 (pre-prompt)",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )
    negative_prompt = ui.TextInput(
        label="네거티브 프롬프트",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False,
    )

    def __init__(
        self,
        cog: "NovelAICog",
        message: discord.Message,
        user_id: str,
        original_prompt: str,
        original_negative: str,
        original_pre_positive: str = "",
        original_pre_negative: str = "",
    ):
        super().__init__()
        self.cog = cog
        self.message = message
        self.user_id = user_id
        self.pre_positive.default = original_pre_positive or ""
        self.prompt.default = original_prompt
        self.pre_negative.default = original_pre_negative or ""
        self.negative_prompt.default = original_negative or ""

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        new_prompt = self.prompt.value
        new_negative = self.negative_prompt.value or ""
        new_pre_pos = self.pre_positive.value or ""
        new_pre_neg = self.pre_negative.value or ""

        stored = self.cog._get_image_params(self.user_id)
        appearance = stored.get("_random_appearance", "")
        used_model = stored.get("model", "nai-diffusion-4-5")
        used_action = stored.get("_last_action", "generate")

        stored["_last_prompt"] = new_prompt
        stored["negative_prompt"] = new_negative
        stored["_pre_positive"] = new_pre_pos
        stored["_pre_negative"] = new_pre_neg
        self.cog._save_params()

        used_prompt = ", ".join(p for p in [new_pre_pos, appearance, new_prompt] if p)
        api_params = {k: v for k, v in stored.items() if k not in _INTERNAL_KEYS}
        combined_negative = ", ".join(p for p in [new_pre_neg, new_negative] if p)
        if combined_negative:
            api_params["negative_prompt"] = combined_negative
        else:
            api_params.pop("negative_prompt", None)

        try:
            images = await novelai_client.generate_image(
                input_text=used_prompt,
                model=used_model,
                action=used_action,
                params=api_params,
            )
            if not images:
                await interaction.followup.send("이미지를 생성하지 못했습니다.", ephemeral=True)
                return
            files = [
                discord.File(io.BytesIO(img), filename=f"result_{i}.png")
                for i, img in enumerate(images)
            ]
            content = _build_prompt_display(new_prompt, new_negative, new_pre_pos, new_pre_neg, appearance)
            view = NAIRegenerateView(self.cog, self.user_id, new_prompt, new_negative)
            await self.message.edit(content=content or None, attachments=files, view=view)
            view.message = self.message
        except Exception as e:
            logger.exception(
                "nai 재생성 오류 | user=%s prompt=%r model=%s action=%s params=%r",
                self.user_id, used_prompt, used_model, used_action, api_params,
            )
            await interaction.followup.send(
                format_error(
                    e,
                    user=f"(ID: {self.user_id})",
                    prompt=used_prompt,
                    model=used_model,
                    action=used_action,
                    api_params=api_params,
                ),
                ephemeral=True,
            )


class NAIRegenerateView(ui.View):
    def __init__(
        self,
        cog: "NovelAICog",
        user_id: str,
        original_prompt: str,
        original_negative: str,
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.original_prompt = original_prompt
        self.original_negative = original_negative
        self.message: Optional[discord.Message] = None

    def _is_owner(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @ui.button(label="프롬프트 수정", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def edit_button(self, interaction: discord.Interaction, button: ui.Button):
        if not self._is_owner(interaction):
            await interaction.response.send_message(
                "다른 사용자가 생성한 이미지는 수정할 수 없습니다.", ephemeral=True
            )
            return
        stored = self.cog._get_image_params(self.user_id)
        modal = NAIPromptModal(
            self.cog,
            self.message or interaction.message,
            self.user_id,
            self.original_prompt,
            self.original_negative,
            original_pre_positive=stored.get("_pre_positive", ""),
            original_pre_negative=stored.get("_pre_negative", ""),
        )
        await interaction.response.send_modal(modal)

    @ui.button(label="외형 재생성", style=discord.ButtonStyle.primary, emoji="🎲")
    async def reroll_button(self, interaction: discord.Interaction, button: ui.Button):
        if not self._is_owner(interaction):
            await interaction.response.send_message(
                "다른 사용자가 생성한 이미지는 수정할 수 없습니다.", ephemeral=True
            )
            return

        await interaction.response.defer()

        stored = self.cog._get_image_params(self.user_id)
        new_appearance = generate_appearance()
        stored["_random_appearance"] = new_appearance
        self.cog._save_params()

        pre_pos = stored.get("_pre_positive", "")
        pre_neg = stored.get("_pre_negative", "")
        last_prompt = stored.get("_last_prompt", "")
        post_negative = stored.get("negative_prompt", "")
        used_model = stored.get("model", "nai-diffusion-4-5")
        used_action = stored.get("_last_action", "generate")

        used_prompt = ", ".join(p for p in [pre_pos, new_appearance, last_prompt] if p)
        api_params = {k: v for k, v in stored.items() if k not in _INTERNAL_KEYS}
        combined_negative = ", ".join(p for p in [pre_neg, post_negative] if p)
        if combined_negative:
            api_params["negative_prompt"] = combined_negative
        else:
            api_params.pop("negative_prompt", None)

        target = interaction.message

        try:
            images = await novelai_client.generate_image(
                input_text=used_prompt,
                model=used_model,
                action=used_action,
                params=api_params,
            )
            if not images:
                await interaction.followup.send("이미지를 생성하지 못했습니다.", ephemeral=True)
                return
            files = [
                discord.File(io.BytesIO(img), filename=f"result_{i}.png")
                for i, img in enumerate(images)
            ]
            content = _build_prompt_display(last_prompt, post_negative, pre_pos, pre_neg, new_appearance)
            view = NAIRegenerateView(self.cog, self.user_id, last_prompt, post_negative)
            await target.edit(content=content or None, attachments=files, view=view)
            view.message = target
        except Exception as e:
            logger.exception(
                "nai 외형 재생성 오류 | user=%s prompt=%r model=%s action=%s params=%r",
                self.user_id, used_prompt, used_model, used_action, api_params,
            )
            await interaction.followup.send(
                format_error(
                    e,
                    user=f"(ID: {self.user_id})",
                    prompt=used_prompt,
                    model=used_model,
                    action=used_action,
                    api_params=api_params,
                ),
                ephemeral=True,
            )


class NovelAICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._image_params: dict[str, dict] = self._load_params()

    @staticmethod
    def _load_params() -> dict:
        if not PARAMS_PATH.exists():
            return {}
        try:
            return json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_params(self):
        PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PARAMS_PATH.write_text(
            json.dumps(self._image_params, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_image_params(self, user_id: str) -> dict:
        return self._image_params.setdefault(user_id, {})

    def _check_whitelist(self, interaction: discord.Interaction):
        if not whitelist_only(interaction):
            raise app_commands.CheckFailure("이 명령어는 허가된 사용자만 사용할 수 있습니다.")

    @app_commands.command(name="nai", description="NovelAI로 이미지를 생성합니다.")
    @app_commands.describe(
        prompt="포지티브 프롬프트 (생략 시 마지막 사용값 재사용)",
        negative_prompt="네거티브 프롬프트 (생략 시 마지막 사용값 재사용)",
        model="모델 (생략 시 마지막 사용값 재사용)",
        action="동작 종류 (생략 시 마지막 사용값 재사용)",
    )
    @app_commands.choices(model=[
        app_commands.Choice(name="nai-diffusion-4-5-full", value="nai-diffusion-4-5-full"),
        app_commands.Choice(name="nai-diffusion-4-5", value="nai-diffusion-4-5"),
        app_commands.Choice(name="nai-diffusion-4-5-curated", value="nai-diffusion-4-5-curated"),
        app_commands.Choice(name="nai-diffusion-4", value="nai-diffusion-4"),
        app_commands.Choice(name="nai-diffusion-4-curated-preview", value="nai-diffusion-4-curated-preview"),
        app_commands.Choice(name="nai-diffusion-3", value="nai-diffusion-3"),
    ])
    @app_commands.choices(action=[
        app_commands.Choice(name="generate", value="generate"),
        app_commands.Choice(name="img2img", value="img2img"),
        app_commands.Choice(name="infill", value="infill"),
    ])
    async def nai(
        self,
        interaction: discord.Interaction,
        prompt: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        model: Optional[str] = None,
        action: Optional[str] = None,
    ):
        self._check_whitelist(interaction)
        await interaction.response.defer(thinking=True)
        user_id = str(interaction.user.id)
        stored = self._get_image_params(user_id)

        pre_positive = stored.get("_pre_positive", "")
        pre_negative = stored.get("_pre_negative", "")
        appearance = stored.get("_random_appearance", "")

        post_positive = prompt or stored.get("_last_prompt", "")

        if not post_positive and not pre_positive and not appearance:
            await interaction.followup.send(
                "프롬프트를 입력하거나 먼저 한 번 이상 사용해야 합니다.", ephemeral=True
            )
            return

        used_prompt = ", ".join(p for p in [pre_positive, appearance, post_positive] if p)
        used_model = model or stored.get("model", "nai-diffusion-4-5")
        used_action = action or stored.get("_last_action", "generate")

        if negative_prompt is not None:
            stored["negative_prompt"] = negative_prompt

        api_params = {k: v for k, v in stored.items() if k not in _INTERNAL_KEYS}

        post_negative = stored.get("negative_prompt", "")
        combined_negative = ", ".join(p for p in [pre_negative, post_negative] if p)
        if combined_negative:
            api_params["negative_prompt"] = combined_negative
        else:
            api_params.pop("negative_prompt", None)

        stored["_last_prompt"] = post_positive
        stored["_last_action"] = used_action
        stored["model"] = used_model
        self._save_params()

        try:
            images = await novelai_client.generate_image(
                input_text=used_prompt,
                model=used_model,
                action=used_action,
                params=api_params,
            )
            if not images:
                await interaction.followup.send("이미지를 생성하지 못했습니다.")
                return
            files = [
                discord.File(io.BytesIO(img), filename=f"result_{i}.png")
                for i, img in enumerate(images)
            ]
            content = _build_prompt_display(post_positive, post_negative, pre_positive, pre_negative, appearance)
            view = NAIRegenerateView(self, user_id, post_positive, post_negative)
            message = await interaction.followup.send(content=content or None, files=files, view=view)
            view.message = message
        except Exception as e:
            logger.exception(
                "nai 오류 | user=%s prompt=%r model=%s action=%s params=%r",
                user_id, used_prompt, used_model, used_action, api_params,
            )
            await interaction.followup.send(
                format_error(
                    e,
                    user=f"{interaction.user} (ID: {user_id})",
                    prompt=used_prompt,
                    model=used_model,
                    action=used_action,
                    api_params=api_params,
                ),
                ephemeral=True,
            )

    @app_commands.command(name="nai_preset", description="이미지 생성 세팅을 프리셋으로 한번에 적용합니다.")
    @app_commands.describe(preset="적용할 프리셋")
    @app_commands.choices(preset=[
        app_commands.Choice(name="landscape (1216×832)", value="landscape"),
        app_commands.Choice(name="portrait (832×1216)", value="portrait"),
    ])
    async def nai_preset(self, interaction: discord.Interaction, preset: str):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        stored = self._get_image_params(user_id)
        for k in list(stored.keys()):
            if k not in _INTERNAL_KEYS:
                del stored[k]
        stored.update(IMAGE_PRESETS[preset])
        self._save_params()
        p = IMAGE_PRESETS[preset]
        await interaction.response.send_message(
            f"**{preset}** 프리셋 적용됨\n"
            f"model=`{p['model']}`  width=`{p['width']}`  height=`{p['height']}`\n"
            f"sampler=`{p['sampler']}`  noise_schedule=`{p['noise_schedule']}`\n"
            f"steps=`{p['steps']}`  scale=`{p['scale']}`  cfg_rescale=`{p['cfg_rescale']}`",
            ephemeral=True,
        )

    @app_commands.command(name="nai_set", description="이미지 파라미터를 설정·조회·초기화합니다.")
    @app_commands.describe(
        key="파라미터 이름 (생략 시 전체 보기, 'clear'로 전체 초기화)",
        value="설정할 값 (생략 시 현재 값 조회, 'clear'로 해당 파라미터 제거)",
    )
    @app_commands.autocomplete(key=nai_key_autocomplete, value=nai_value_autocomplete)
    async def nai_set(
        self,
        interaction: discord.Interaction,
        key: Optional[str] = None,
        value: Optional[str] = None,
    ):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        stored = self._get_image_params(user_id)

        if key is None:
            display = {k: v for k, v in stored.items() if k not in _INTERNAL_KEYS}
            if not display:
                await interaction.response.send_message("설정된 파라미터가 없습니다.", ephemeral=True)
                return
            lines = [f"**{k}:** `{v}`" for k, v in display.items()]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        if key == "clear":
            self._image_params.pop(user_id, None)
            self._save_params()
            await interaction.response.send_message("이미지 파라미터가 초기화되었습니다.", ephemeral=True)
            return

        if key not in IMAGE_PARAM_TYPES:
            valid = ", ".join(f"`{k}`" for k in IMAGE_PARAM_KEYS)
            await interaction.response.send_message(
                f"알 수 없는 파라미터: `{key}`\n유효한 파라미터: {valid}", ephemeral=True
            )
            return

        if value is None:
            current_val = stored.get(key)
            hint = IMAGE_PARAM_VALUE_HINTS.get(key, "")
            hint_str = f"  ({hint})" if hint else ""
            if current_val is not None:
                await interaction.response.send_message(
                    f"**{key}:** `{current_val}`{hint_str}", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"**{key}:** 설정되지 않음{hint_str}", ephemeral=True
                )
            return

        if value == "clear":
            stored.pop(key, None)
            self._save_params()
            await interaction.response.send_message(f"파라미터 `{key}`가 제거되었습니다.", ephemeral=True)
            return

        type_name = IMAGE_PARAM_TYPES[key]
        try:
            if type_name == "str":
                parsed = value
            elif type_name == "int":
                parsed = int(value)
            elif type_name == "float":
                parsed = float(value)
            elif type_name == "bool":
                if value.lower() in ("true", "1", "yes"):
                    parsed = True
                elif value.lower() in ("false", "0", "no"):
                    parsed = False
                else:
                    raise ValueError("true 또는 false 중 하나여야 합니다")
            else:
                parsed = value
        except ValueError as e:
            hint = IMAGE_PARAM_VALUE_HINTS.get(key, "")
            hint_str = f"\n예상 형식: {hint}" if hint else ""
            await interaction.response.send_message(
                f"잘못된 값: `{value}`{hint_str}\n오류: {e}", ephemeral=True
            )
            return

        stored[key] = parsed
        self._save_params()
        await interaction.response.send_message(f"`{key}` = `{parsed}`", ephemeral=True)

    @app_commands.command(name="nai_pre", description="선행 프롬프트(그림체 프리셋)를 설정·확인·초기화합니다.")
    @app_commands.describe(
        positive="선행 포지티브 프롬프트 (생략 시 유지)",
        negative="선행 네거티브 프롬프트 (생략 시 유지)",
        action="show=확인 / clear=초기화 (positive/negative 입력 시 자동으로 설정)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="show (현재 확인)", value="show"),
        app_commands.Choice(name="clear (초기화)", value="clear"),
    ])
    async def nai_pre(
        self,
        interaction: discord.Interaction,
        positive: Optional[str] = None,
        negative: Optional[str] = None,
        action: Optional[str] = None,
    ):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        stored = self._get_image_params(user_id)

        if action == "clear":
            stored.pop("_pre_positive", None)
            stored.pop("_pre_negative", None)
            self._save_params()
            await interaction.response.send_message("선행 프롬프트가 초기화되었습니다.", ephemeral=True)
            return

        if action == "show" or (positive is None and negative is None):
            pre_pos = stored.get("_pre_positive") or "(없음)"
            pre_neg = stored.get("_pre_negative") or "(없음)"
            await interaction.response.send_message(
                f"**선행 포지티브:** {pre_pos}\n**선행 네거티브:** {pre_neg}",
                ephemeral=True,
            )
            return

        if positive is not None:
            stored["_pre_positive"] = positive
        if negative is not None:
            stored["_pre_negative"] = negative
        self._save_params()
        lines = []
        if positive is not None:
            lines.append(f"**선행 포지티브:** {positive}")
        if negative is not None:
            lines.append(f"**선행 네거티브:** {negative}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(NovelAICog(bot))
