import io
import json
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.config import settings
from bot.core.novelai_client import novelai_client
from bot.core.error_utils import format_error, send_long
from bot.core.nai_image_utils import crop_and_resize, image_to_base64

logger = logging.getLogger(__name__)

PRECISE_REFS_PATH = Path("data/precise_refs.json")
MAX_REFS = 3  # NAI API 최대 허용 레퍼런스 수

# Precise Reference는 V4.5 전용
_V4_5_MODELS = {
    "nai-diffusion-4-5",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-5-full",
}

_INTERNAL_KEYS = {
    "_last_prompt",
    "_last_action",
    "model",
    "_pre_positive",
    "_pre_negative",
    "_random_appearance",
    "_random_config",
}


def _build_director_params(refs: list[dict]) -> dict:
    """저장된 레퍼런스 목록에서 NAI API director_reference_* 파라미터를 생성한다."""
    return {
        "director_reference_images": [r["image_b64"] for r in refs],
        "director_reference_descriptions": [
            {
                "caption": {
                    "base_caption": r["type"],
                    "char_captions": [],
                },
                "legacy_uc": False,
            }
            for r in refs
        ],
        "director_reference_strength_values": [
            round(r.get("strength", 1.0), 2) for r in refs
        ],
        "director_reference_secondary_strength_values": [
            round(1.0 - r.get("fidelity", 1.0), 2) for r in refs
        ],
        "director_reference_information_extracted": [1.0] * len(refs),
    }


class PreciseRefCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._refs: dict[str, list[dict]] = self._load_refs()
        self._image_params_path = Path("data/image_params.json")

    # ─── 저장/로드 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _load_refs() -> dict:
        if not PRECISE_REFS_PATH.exists():
            return {}
        try:
            return json.loads(PRECISE_REFS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_refs(self):
        PRECISE_REFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PRECISE_REFS_PATH.write_text(
            json.dumps(self._refs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_refs(self, user_id: str) -> list[dict]:
        return self._refs.setdefault(user_id, [])

    def _get_image_params(self, user_id: str) -> dict:
        """novelai_cog이 저장한 image_params에서 사용자 설정을 읽는다."""
        if not self._image_params_path.exists():
            return {}
        try:
            data = json.loads(self._image_params_path.read_text(encoding="utf-8"))
            return data.get(user_id, {})
        except Exception:
            return {}

    def _check_whitelist(self, interaction: discord.Interaction):
        if interaction.user.id not in settings.whitelist_ids:
            raise app_commands.CheckFailure(
                "이 명령어는 허가된 사용자만 사용할 수 있습니다."
            )

    # ─── Reference 관리 커맨드 ──────────────────────────────────────────────────

    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.command(
        name="nai_ref_add",
        description="Precise Reference 이미지를 추가합니다. (최대 3개, V4.5 모델 전용)",
    )
    @app_commands.describe(
        image="참조할 이미지 첨부파일",
        ref_type="레퍼런스 유형",
        fidelity="캐릭터 충실도 — 높을수록 참조 이미지와 유사 (0.0~1.0, 기본 1.0)",
        strength="레퍼런스 강도 (0.0~1.0, 기본 1.0)",
        label="레퍼런스 식별 이름 (선택)",
    )
    @app_commands.choices(
        ref_type=[
            app_commands.Choice(name="캐릭터 & 스타일 (기본)", value="character&style"),
            app_commands.Choice(name="캐릭터만", value="character"),
            app_commands.Choice(name="스타일만", value="style"),
        ]
    )
    async def nai_ref_add(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment,
        ref_type: str = "character&style",
        fidelity: float = 1.0,
        strength: float = 1.0,
        label: Optional[str] = None,
    ):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        refs = self._get_refs(user_id)

        if len(refs) >= MAX_REFS:
            await interaction.response.send_message(
                f"Precise Reference는 최대 {MAX_REFS}개까지 등록 가능합니다. "
                "`/nai_ref_remove` 또는 `/nai_ref_clear`로 먼저 제거해주세요.",
                ephemeral=True,
            )
            return

        if not image.content_type or not image.content_type.startswith("image/"):
            await interaction.response.send_message(
                "이미지 파일(PNG, JPG 등)을 첨부해주세요.", ephemeral=True
            )
            return

        fidelity = max(0.0, min(1.0, fidelity))
        strength = max(0.0, min(1.0, strength))

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            img_bytes = await image.read()
            # novelai-sdk: bytes → base64 → crop & resize (1024×1536, 레터박스)
            b64 = image_to_base64(img_bytes)
            b64_processed = crop_and_resize(b64)
        except Exception as e:
            logger.exception("nai_ref_add 이미지 처리 오류 | user=%s", user_id)
            await interaction.followup.send(
                f"이미지 처리 중 오류가 발생했습니다: `{e}`", ephemeral=True
            )
            return

        entry_label = label.strip() if label else f"ref_{len(refs) + 1}"
        refs.append(
            {
                "image_b64": b64_processed,
                "type": ref_type,
                "fidelity": fidelity,
                "strength": strength,
                "label": entry_label,
            }
        )
        self._save_refs()

        await interaction.followup.send(
            f"Precise Reference [{len(refs)}] 추가됨\n"
            f"label=`{entry_label}`  type=`{ref_type}`  "
            f"fidelity=`{fidelity}`  strength=`{strength}`",
            ephemeral=True,
        )

    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.command(
        name="nai_ref_list",
        description="등록된 Precise Reference 목록을 조회합니다.",
    )
    async def nai_ref_list(self, interaction: discord.Interaction):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        refs = self._get_refs(user_id)

        if not refs:
            await interaction.response.send_message(
                "등록된 Precise Reference가 없습니다.", ephemeral=True
            )
            return

        lines = [f"**Precise Reference 목록** ({len(refs)}/{MAX_REFS})"]
        for i, r in enumerate(refs, 1):
            lines.append(
                f"**[{i}]** `{r.get('label', f'ref_{i}')}` — "
                f"type=`{r['type']}`  "
                f"fidelity=`{r.get('fidelity', 1.0)}`  "
                f"strength=`{r.get('strength', 1.0)}`"
            )
        await send_long(interaction, "\n".join(lines), ephemeral=True)

    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.command(
        name="nai_ref_remove",
        description="특정 Precise Reference를 제거합니다.",
    )
    @app_commands.describe(index="제거할 레퍼런스 번호 (1부터 시작)")
    async def nai_ref_remove(self, interaction: discord.Interaction, index: int):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        refs = self._get_refs(user_id)

        if not refs:
            await interaction.response.send_message(
                "등록된 Precise Reference가 없습니다.", ephemeral=True
            )
            return

        if index < 1 or index > len(refs):
            await interaction.response.send_message(
                f"유효한 번호를 입력해주세요 (1~{len(refs)}).", ephemeral=True
            )
            return

        removed = refs.pop(index - 1)
        self._save_refs()
        await interaction.response.send_message(
            f"Precise Reference [{index}] `{removed.get('label', f'ref_{index}')}` 제거됨.",
            ephemeral=True,
        )

    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.command(
        name="nai_ref_clear",
        description="모든 Precise Reference를 초기화합니다.",
    )
    async def nai_ref_clear(self, interaction: discord.Interaction):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)
        self._refs.pop(user_id, None)
        self._save_refs()
        await interaction.response.send_message(
            "Precise Reference가 초기화되었습니다.", ephemeral=True
        )

    # ─── 생성 커맨드 ────────────────────────────────────────────────────────────

    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.command(
        name="nai_precise",
        description="Precise Reference를 적용해 이미지를 생성합니다. (V4.5 모델 전용)",
    )
    @app_commands.describe(
        prompt="포지티브 프롬프트 (생략 시 /nai에서 마지막 사용값 재사용)",
    )
    async def nai_precise(
        self,
        interaction: discord.Interaction,
        prompt: Optional[str] = None,
    ):
        self._check_whitelist(interaction)
        user_id = str(interaction.user.id)

        refs = self._get_refs(user_id)
        if not refs:
            await interaction.response.send_message(
                "등록된 Precise Reference가 없습니다. "
                "`/nai_ref_add`로 이미지를 먼저 추가해주세요.",
                ephemeral=True,
            )
            return

        stored = self._get_image_params(user_id)
        pre_positive = stored.get("_pre_positive", "")
        pre_negative = stored.get("_pre_negative", "")
        post_positive = prompt.strip() if prompt else stored.get("_last_prompt", "")

        if not post_positive and not pre_positive:
            await interaction.response.send_message(
                "프롬프트를 입력하거나 `/nai`를 먼저 한 번 이상 사용해야 합니다.",
                ephemeral=True,
            )
            return

        used_model = stored.get("model", "nai-diffusion-4-5-full")
        if used_model not in _V4_5_MODELS:
            await interaction.response.send_message(
                f"Precise Reference는 V4.5 모델에서만 지원됩니다.\n"
                f"현재 모델: `{used_model}`\n"
                f"지원 모델: {', '.join(f'`{m}`' for m in sorted(_V4_5_MODELS))}",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        used_prompt = ", ".join(p for p in [pre_positive, post_positive] if p)

        api_params = {k: v for k, v in stored.items() if k not in _INTERNAL_KEYS}
        post_negative = stored.get("negative_prompt", "")
        combined_negative = ", ".join(p for p in [pre_negative, post_negative] if p)
        if combined_negative:
            api_params["negative_prompt"] = combined_negative
        else:
            api_params.pop("negative_prompt", None)

        # novelai-sdk가 정의한 director reference 파라미터 주입
        api_params.update(_build_director_params(refs))

        try:
            images = await novelai_client.generate_image(
                input_text=used_prompt,
                model=used_model,
                action="generate",
                params=api_params,
            )
        except Exception as e:
            logger.exception(
                "nai_precise 오류 | user=%s prompt=%r model=%s refs=%d",
                user_id,
                used_prompt,
                used_model,
                len(refs),
            )
            await interaction.followup.send(
                format_error(
                    e,
                    user=f"{interaction.user} (ID: {user_id})",
                    prompt=used_prompt,
                    model=used_model,
                ),
                ephemeral=True,
            )
            return

        if not images:
            await interaction.followup.send("이미지를 생성하지 못했습니다.")
            return

        ref_summary = " / ".join(
            f"`{r.get('label', f'ref_{i + 1}')}`({r['type']})"
            for i, r in enumerate(refs)
        )
        files = [
            discord.File(io.BytesIO(img), filename=f"precise_{i}.png")
            for i, img in enumerate(images)
        ]
        content = f"-# Precise Ref: {ref_summary}"
        if post_positive:
            content += f"\n`{post_positive}`"

        await interaction.followup.send(content=content, files=files)


async def setup(bot: commands.Bot):
    await bot.add_cog(PreciseRefCog(bot))
