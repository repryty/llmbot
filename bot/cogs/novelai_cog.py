import asyncio
import io
import json
import re
import logging
import zipfile
from pathlib import Path
from typing import Optional
import httpx
import discord
from discord.ext import commands
from discord import app_commands, ui

from bot.core.config import settings
from bot.core.novelai_client import novelai_client
from bot.core.error_utils import format_error, send_long
from bot.core.appearance_gen import generate_appearance, WEIGHT_DEFAULTS

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
# _random_appearance         : 구버전 호환용 (더 이상 사용하지 않음, API 전달 방지용으로만 유지)
# _random_config             : 랜덤 생성 가중치 설정
_INTERNAL_KEYS = {
    "_last_prompt", "_last_action", "model",
    "_pre_positive", "_pre_negative", "_random_appearance",
    "_random_config",
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


# (type, default, description)
RANDOM_WEIGHT_KEYS: dict[str, tuple] = {
    "p_animal":      ("float", 0.10, "동물 특징(귀·꼬리·뿔 등) 생성 확률 [0.0~1.0]  기본 0.10"),
    "p_skin":        ("float", 0.40, "피부 색상 생성 확률 [0.0~1.0]  기본 0.40"),
    "p_eye_color":   ("float", 0.80, "눈 색상 생성 확률 [0.0~1.0]  기본 0.80"),
    "p_eye_style":   ("float", 0.15, "눈 스타일(이색동공·하트눈 등) 생성 확률 [0.0~1.0]  기본 0.15"),
    "p_eye_expr":    ("float", 0.25, "눈 표정(타레메·지토메 등) 생성 확률 [0.0~1.0]  기본 0.25"),
    "p_hair_length": ("float", 0.80, "머리 길이 생성 확률 [0.0~1.0]  기본 0.80"),
    "p_hair_color":  ("float", 0.70, "머리 색상 생성 확률 [0.0~1.0]  기본 0.70"),
    "p_hair_multi":  ("float", 0.10, "다색 머리(그라데이션·레인보우 등) 생성 확률 [0.0~1.0]  기본 0.10"),
    "p_braid":       ("float", 0.50, "묶음 스타일(포니테일·트윈테일 등) 생성 확률 [0.0~1.0]  기본 0.50"),
    "p_hair_style":  ("float", 0.15, "머리 텍스처(웨이브·곱슬 등) 생성 확률 [0.0~1.0]  기본 0.15"),
    "p_bangs":       ("float", 0.25, "앞머리 스타일 생성 확률 [0.0~1.0]  기본 0.25"),
    "p_hair_acc":    ("float", 0.25, "머리 악세서리(리본·핀 등) 생성 확률 [0.0~1.0]  기본 0.25"),
    "p_breast":      ("float", 0.50, "가슴 크기 생성 확률 (gender=f 전용) [0.0~1.0]  기본 0.50"),
    "p_expression":  ("float", 0.60, "얼굴 표정 생성 확률 [0.0~1.0]  기본 0.60"),
    "p_dress":       ("float", 0.25, "드레스·교복·기모노 등 원피스 계열 확률 [0.0~1.0]  기본 0.25"),
    "p_swimwear":    ("float", 0.05, "수영복 확률 (드레스 미선택 시) [0.0~1.0]  기본 0.05"),
    "p_bodysuit":    ("float", 0.05, "바디수트·레오타드 확률 (드레스·수영복 미선택 시) [0.0~1.0]  기본 0.05"),
    "p_top":         ("float", 0.75, "상의(셔츠·블라우스·후드 등) 생성 확률 [0.0~1.0]  기본 0.75"),
    "p_bottom":      ("float", 0.60, "하의(스커트·반바지·바지 등) 생성 확률 [0.0~1.0]  기본 0.60"),
    "p_outerwear":   ("float", 0.30, "아우터(재킷·코트·망토 등) 생성 확률 [0.0~1.0]  기본 0.30"),
    "p_hosiery":     ("float", 0.50, "스타킹·양말 생성 확률 [0.0~1.0]  기본 0.50"),
    "p_footwear":    ("float", 0.55, "신발·부츠 생성 확률 [0.0~1.0]  기본 0.55"),
    "p_headwear":    ("float", 0.15, "모자·왕관 등 머리 장식 생성 확률 [0.0~1.0]  기본 0.15"),
    "p_accessory":   ("float", 0.35, "장갑·초커·넥타이·앞치마 등 악세서리 생성 확률 [0.0~1.0]  기본 0.35"),
    "gender":        ("str",   "f",  "성별 (f=여성 / m=남성)  기본 f"),
    "only_face":     ("bool",  False, "얼굴·머리 태그만 생성 / 신체 제외 여부  기본 false"),
}


def _parse_prompt_line(line: str) -> tuple[str, int]:
    """'텍스트 x N' → (텍스트, N). 숫자만 → ("", N). 그 외 → (텍스트, 1)."""
    m = re.match(r'^(.*?)\s+[xX]\s+(\d+)\s*$', line)
    if m:
        return m.group(1).strip(), max(1, int(m.group(2)))
    if re.fullmatch(r'\d+', line.strip()):
        return "", max(1, int(line.strip()))
    return line.strip(), 1


def _strip_code_block(text: str) -> str:
    """` 또는 ```로 감싸진 코드블럭 마커를 제거하고 내용만 반환합니다.

    감싸지 않은 텍스트는 그대로 반환합니다.
    트리플 백틱의 경우 선택적 언어 식별자(```python 등)도 함께 제거됩니다.
    """
    if not text:
        return text
    s = text.strip()
    # 트리플 백틱: ```[언어]\n내용\n``` 또는 ```내용```
    m = re.fullmatch(r'```(?:[^\n]*\n)?([\s\S]*?)```', s)
    if m:
        return m.group(1).strip()
    # 단일 백틱: `내용`
    m = re.fullmatch(r'`([^`]*)`', s)
    if m:
        return m.group(1).strip()
    return s


async def random_key_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    choices = ["clear"] + list(RANDOM_WEIGHT_KEYS.keys())
    return [
        app_commands.Choice(name=k, value=k)
        for k in choices
        if current.lower() in k.lower()
    ][:25]


async def random_value_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    key = interaction.namespace.key or ""
    if key == "gender":
        suggestions = ["f", "m", "clear"]
    elif key == "only_face":
        suggestions = ["false", "true", "clear"]
    elif key in RANDOM_WEIGHT_KEYS:
        _, default, _ = RANDOM_WEIGHT_KEYS[key]
        suggestions = [str(default), "clear"]
    else:
        suggestions = ["clear"]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions
        if current.lower() in s.lower()
    ][:25]


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
        new_prompt = _strip_code_block(self.prompt.value)
        new_negative = _strip_code_block(self.negative_prompt.value or "")
        new_pre_pos = _strip_code_block(self.pre_positive.value or "")
        new_pre_neg = _strip_code_block(self.pre_negative.value or "")

        stored = self.cog._get_image_params(self.user_id)
        used_model = stored.get("model", "nai-diffusion-4-5")
        used_action = stored.get("_last_action", "generate")

        stored["_last_prompt"] = new_prompt
        stored["negative_prompt"] = new_negative
        stored["_pre_positive"] = new_pre_pos
        stored["_pre_negative"] = new_pre_neg
        self.cog._save_params()

        used_prompt = ", ".join(p for p in [new_pre_pos, new_prompt] if p)
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
            view = NAIRegenerateView(self.cog, self.user_id, new_prompt, new_negative)
            await self.message.edit(content=None, attachments=files, view=view)
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
        super().__init__(timeout=600)
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
        new_appearance = generate_appearance(config=stored.get("_random_config"))
        stored["_last_prompt"] = new_appearance
        self.cog._save_params()

        pre_pos = stored.get("_pre_positive", "")
        pre_neg = stored.get("_pre_negative", "")
        post_negative = stored.get("negative_prompt", "")
        used_model = stored.get("model", "nai-diffusion-4-5")
        used_action = stored.get("_last_action", "generate")

        used_prompt = ", ".join(p for p in [pre_pos, new_appearance] if p)
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
            view = NAIRegenerateView(self.cog, self.user_id, new_appearance, post_negative)
            await target.edit(content=None, attachments=files, view=view)
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


BATCH_MIN_INTERVAL = 3.0
BATCH_MAX_INTERVAL = 60.0


class NAIBatchModal(ui.Modal, title="NAI 배치 생성"):
    prompts_input = ui.TextInput(
        label="프롬프트 목록 ('텍스트 x N' 형식 / 랜덤: 숫자만)",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True,
        placeholder="red hair, 1girl x 5\nblue hair, 1girl x 3\n(랜덤 외형 ON이면 숫자만: 10)",
    )
    interval_input = ui.TextInput(
        label="호출 간격 (초, 3~60)",
        style=discord.TextStyle.short,
        max_length=3,
        required=False,
        default="5",
    )
    random_app_input = ui.TextInput(
        label="랜덤 외형 매번 재생성 (y / n)",
        style=discord.TextStyle.short,
        max_length=3,
        required=False,
        default="n",
    )

    def __init__(self, cog: "NovelAICog", user_id: str):
        super().__init__()
        self.cog = cog
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            interval = max(
                BATCH_MIN_INTERVAL,
                min(BATCH_MAX_INTERVAL, float(self.interval_input.value.strip() or "5")),
            )
        except ValueError:
            await interaction.response.send_message(
                f"간격은 {BATCH_MIN_INTERVAL:.0f}~{BATCH_MAX_INTERVAL:.0f} 사이 숫자여야 합니다.",
                ephemeral=True,
            )
            return

        use_random = self.random_app_input.value.strip().lower() in ("y", "yes", "true", "1")

        raw_input = _strip_code_block(self.prompts_input.value)
        raw_lines = [l.strip() for l in raw_input.splitlines() if l.strip()]
        if not raw_lines:
            await interaction.response.send_message("내용을 입력해주세요.", ephemeral=True)
            return

        jobs: list[tuple[str, int]] = []
        for line in raw_lines:
            text, count = _parse_prompt_line(line)
            text = _strip_code_block(text)
            if use_random:
                jobs.append(("", count))
            else:
                if text:
                    jobs.append((text, count))

        if not jobs:
            await interaction.response.send_message(
                "유효한 프롬프트를 입력해주세요. (랜덤 외형 OFF 시 텍스트 필요)", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        await self.cog._run_batch(interaction, self.user_id, jobs, interval, use_random)


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

        post_positive = _strip_code_block(prompt) if prompt is not None else stored.get("_last_prompt", "")

        if not post_positive and not pre_positive:
            await interaction.followup.send(
                "프롬프트를 입력하거나 먼저 한 번 이상 사용해야 합니다.", ephemeral=True
            )
            return

        used_prompt = ", ".join(p for p in [pre_positive, post_positive] if p)
        used_model = model or stored.get("model", "nai-diffusion-4-5")
        used_action = action or stored.get("_last_action", "generate")

        if negative_prompt is not None:
            stored["negative_prompt"] = _strip_code_block(negative_prompt)

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
            view = NAIRegenerateView(self, user_id, post_positive, post_negative)
            content = f"`{post_positive}`" if post_positive else None
            message = await interaction.followup.send(content=content, files=files, view=view, wait=True)
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
            await send_long(interaction, "\n".join(lines), ephemeral=True)
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
                parsed = _strip_code_block(value)
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
            await send_long(
                interaction,
                f"**선행 포지티브:** {pre_pos}\n**선행 네거티브:** {pre_neg}",
                ephemeral=True,
            )
            return

        if positive is not None:
            positive = _strip_code_block(positive)
            stored["_pre_positive"] = positive
        if negative is not None:
            negative = _strip_code_block(negative)
            stored["_pre_negative"] = negative
        self._save_params()
        lines = []
        if positive is not None:
            lines.append(f"**선행 포지티브:** {positive}")
        if negative is not None:
            lines.append(f"**선행 네거티브:** {negative}")
        await send_long(interaction, "\n".join(lines), ephemeral=True)

    @app_commands.command(name="random", description="랜덤 외형 태그를 생성해 후행 프롬프트에 주입합니다.")
    async def random_appearance(self, interaction: discord.Interaction):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        stored = self._get_image_params(user_id)
        config = stored.get("_random_config")
        result = generate_appearance(config=config)
        stored["_last_prompt"] = result
        self._save_params()
        await interaction.response.send_message(
            f"외형 생성됨 (포지티브 프롬프트에 저장)\n`{result}`",
            ephemeral=True,
        )

    @app_commands.command(name="nai_prompt", description="현재 저장된 프롬프트를 열람합니다.")
    async def nai_prompt(self, interaction: discord.Interaction):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        stored = self._get_image_params(user_id)

        pre_pos = stored.get("_pre_positive") or "(없음)"
        last_pos = stored.get("_last_prompt") or "(없음)"
        pre_neg = stored.get("_pre_negative") or "(없음)"
        last_neg = stored.get("negative_prompt") or "(없음)"

        lines = [
            "**📝 저장된 프롬프트**",
            f"**선행 포지티브:**\n{pre_pos}",
            f"**후행 포지티브 (마지막 사용):**\n{last_pos}",
            f"**선행 네거티브:**\n{pre_neg}",
            f"**후행 네거티브:**\n{last_neg}",
        ]
        await send_long(interaction, "\n\n".join(lines), ephemeral=True)

    async def _run_batch(
        self,
        interaction: discord.Interaction,
        user_id: str,
        jobs: list[tuple[str, int]],
        interval: float,
        use_random: bool,
    ):
        total = sum(c for _, c in jobs)
        stored = self._get_image_params(user_id)
        pre_positive = stored.get("_pre_positive", "")
        pre_negative = stored.get("_pre_negative", "")
        used_model = stored.get("model", "nai-diffusion-4-5")
        used_action = stored.get("_last_action", "generate")
        post_negative = stored.get("negative_prompt", "")

        header = (
            f"배치 시작: {total}장"
            f"  |  간격 {interval:.0f}초"
            f"  |  랜덤 외형 {'ON' if use_random else 'OFF'}"
        )
        progress_msg = await interaction.followup.send(f"⏳ {header}\n진행: 0 / {total}")

        completed = 0
        errors = 0
        job_list = [(text, i) for text, count in jobs for i in range(count)]

        for idx, (prompt_text, _) in enumerate(job_list):
            if use_random:
                trailing = generate_appearance(config=stored.get("_random_config"))
                stored["_last_prompt"] = trailing
                self._save_params()
            else:
                trailing = prompt_text

            used_prompt = ", ".join(p for p in [pre_positive, trailing] if p)
            api_params = {k: v for k, v in stored.items() if k not in _INTERNAL_KEYS}
            api_params["n_samples"] = 1
            api_params["seed"] = 0
            combined_negative = ", ".join(p for p in [pre_negative, post_negative] if p)
            if combined_negative:
                api_params["negative_prompt"] = combined_negative
            else:
                api_params.pop("negative_prompt", None)

            label = f"`{trailing}`" if trailing else "(없음)"
            completed += 1

            try:
                images = await novelai_client.generate_image(
                    input_text=used_prompt,
                    model=used_model,
                    action=used_action,
                    params=api_params,
                )
                files = [
                    discord.File(io.BytesIO(img), filename=f"batch_{completed}_{j}.png")
                    for j, img in enumerate(images)
                ]
                prefix = f"**[{completed}/{total}]** "
                msg_content = prefix + label
                if len(msg_content) > 2000:
                    msg_content = prefix + f"`{trailing[:2000 - len(prefix) - 4]}...`"
                await interaction.followup.send(content=msg_content, files=files)
            except Exception as e:
                errors += 1
                logger.exception("nai 배치 오류 | user=%s trailing=%r", user_id, trailing)
                err_prefix = f"**[{completed}/{total}]** "
                err_content = err_prefix + label + f" — 오류: `{e}`"
                if len(err_content) > 2000:
                    err_content = err_prefix + f"`{trailing[:2000 - len(err_prefix) - 4]}...`" + f" — 오류: `{e}`"
                await interaction.followup.send(content=err_content)

            await progress_msg.edit(content=f"⏳ {header}\n진행: {completed} / {total}")

            if idx < len(job_list) - 1:
                await asyncio.sleep(interval)

        suffix = f" (오류 {errors}건)" if errors else ""
        await progress_msg.edit(content=f"✅ 배치 완료: {total}장{suffix}")

    @app_commands.command(name="nai_batch", description="NAI 배치 이미지 생성 (여러 프롬프트를 순차적으로 생성)")
    async def nai_batch(self, interaction: discord.Interaction):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        await interaction.response.send_modal(NAIBatchModal(self, user_id))

    @app_commands.command(name="nai_batch_file", description="텍스트 파일로 NAI 배치 이미지 생성")
    @app_commands.describe(
        file="프롬프트 목록 텍스트 파일 (.txt, 한 줄에 '텍스트 x N' 형식)",
        interval="호출 간격 (초, 3~60, 기본 5)",
        random_app="랜덤 외형 매번 재생성 (y/n, 기본 n)",
    )
    async def nai_batch_file(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        interval: Optional[float] = 5.0,
        random_app: Optional[str] = "n",
    ):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)

        if file.size > 100_000:
            await interaction.response.send_message("파일 크기는 100KB 이하여야 합니다.", ephemeral=True)
            return

        clamped_interval = max(BATCH_MIN_INTERVAL, min(BATCH_MAX_INTERVAL, interval or 5.0))
        use_random = (random_app or "n").strip().lower() in ("y", "yes", "true", "1")

        await interaction.response.defer(thinking=True)

        try:
            raw_bytes = await file.read()
            raw_input = raw_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            await interaction.followup.send(f"파일 읽기 오류: `{e}`", ephemeral=True)
            return

        raw_input = _strip_code_block(raw_input)
        raw_lines = [l.strip() for l in raw_input.splitlines() if l.strip()]
        if not raw_lines:
            await interaction.followup.send("파일에 유효한 내용이 없습니다.", ephemeral=True)
            return

        jobs: list[tuple[str, int]] = []
        for line in raw_lines:
            text, count = _parse_prompt_line(line)
            text = _strip_code_block(text)
            if use_random:
                jobs.append(("", count))
            else:
                if text:
                    jobs.append((text, count))

        if not jobs:
            await interaction.followup.send(
                "유효한 프롬프트가 없습니다. (랜덤 외형 OFF 시 텍스트 필요)", ephemeral=True
            )
            return

        await self._run_batch(interaction, user_id, jobs, clamped_interval, use_random)

    @app_commands.command(name="random_set", description="랜덤 외형 생성 가중치를 설정·조회·초기화합니다.")
    @app_commands.describe(
        key="파라미터 이름 (생략 시 전체 보기, 'clear'로 전체 초기화)",
        value="설정할 값 (생략 시 현재 값과 설명 표시, 'clear'로 기본값으로 리셋)",
    )
    @app_commands.autocomplete(key=random_key_autocomplete, value=random_value_autocomplete)
    async def random_set(
        self,
        interaction: discord.Interaction,
        key: Optional[str] = None,
        value: Optional[str] = None,
    ):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        stored = self._get_image_params(user_id)
        config: dict = stored.setdefault("_random_config", {})

        if key is None:
            lines = []
            for k, (_, default, desc) in RANDOM_WEIGHT_KEYS.items():
                cur = config.get(k, default)
                lines.append(f"**{k}** = `{cur}`  (기본 `{default}`)  — {desc}")
            await send_long(interaction, "\n".join(lines), ephemeral=True)
            return

        if key == "clear":
            stored.pop("_random_config", None)
            self._save_params()
            await interaction.response.send_message("랜덤 가중치가 기본값으로 초기화되었습니다.", ephemeral=True)
            return

        if key not in RANDOM_WEIGHT_KEYS:
            valid = ", ".join(f"`{k}`" for k in RANDOM_WEIGHT_KEYS)
            await interaction.response.send_message(
                f"알 수 없는 파라미터: `{key}`\n유효한 파라미터: {valid}", ephemeral=True
            )
            return

        type_name, default, desc = RANDOM_WEIGHT_KEYS[key]

        if value is None:
            cur = config.get(key, default)
            await interaction.response.send_message(
                f"**{key}** = `{cur}`  (기본 `{default}`)\n{desc}", ephemeral=True
            )
            return

        if value == "clear":
            config.pop(key, None)
            if not config:
                stored.pop("_random_config", None)
            self._save_params()
            await interaction.response.send_message(
                f"`{key}` 기본값(`{default}`)으로 리셋되었습니다.", ephemeral=True
            )
            return

        try:
            if type_name == "float":
                parsed = float(value)
                if not 0.0 <= parsed <= 1.0:
                    raise ValueError("0.0~1.0 사이 값이어야 합니다")
            elif type_name == "bool":
                if value.lower() in ("true", "1", "yes"):
                    parsed = True
                elif value.lower() in ("false", "0", "no"):
                    parsed = False
                else:
                    raise ValueError("true 또는 false 중 하나여야 합니다")
            elif key == "gender":
                if value not in ("f", "m"):
                    raise ValueError("f 또는 m 중 하나여야 합니다")
                parsed = value
            else:
                parsed = value
        except ValueError as e:
            await interaction.response.send_message(
                f"잘못된 값: `{value}`\n오류: {e}\n{desc}", ephemeral=True
            )
            return

        config[key] = parsed
        self._save_params()
        await interaction.response.send_message(f"`{key}` = `{parsed}`", ephemeral=True)


    @app_commands.command(name="nai_zip", description="채널의 최근 n개 이미지를 zip으로 묶어 보냅니다.")
    @app_commands.describe(n="가져올 이미지 개수 (기본 10, 최대 100)")
    async def nai_zip(self, interaction: discord.Interaction, n: Optional[int] = 10):
        self._check_whitelist(interaction)
        n = max(1, min(100, n or 10))
        await interaction.response.defer(thinking=True)

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
            await interaction.followup.send("이 채널에서는 메세지 히스토리를 조회할 수 없습니다.", ephemeral=True)
            return

        collected: list[tuple[str, str]] = []  # (url, filename)
        async for msg in channel.history(limit=500):
            for att in msg.attachments:
                if att.filename.lower().endswith(".png"):
                    collected.append((att.url, att.filename))
                    if len(collected) >= n:
                        break
            if len(collected) >= n:
                break

        if not collected:
            await interaction.followup.send("최근 메세지에서 PNG 이미지를 찾을 수 없습니다.", ephemeral=True)
            return

        buf = io.BytesIO()
        async with httpx.AsyncClient() as client:
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, (url, filename) in enumerate(collected):
                    resp = await client.get(url, timeout=30.0)
                    resp.raise_for_status()
                    zf.writestr(f"{idx + 1:03d}_{filename}", resp.content)
        buf.seek(0)

        await interaction.followup.send(
            f"최근 {len(collected)}개 이미지",
            file=discord.File(buf, filename="images.zip"),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(NovelAICog(bot))
