import io
import json
from pathlib import Path
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands

from bot.core.config import settings
from bot.core.novelai_client import novelai_client

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
_INTERNAL_KEYS = {"_last_prompt", "_last_action", "model"}


class NovelAICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._image_params: dict[str, dict] = self._load_params()

    # ---------- 영속성 ----------

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

    # ---------- 헬퍼 ----------

    def _get_image_params(self, user_id: str) -> dict:
        return self._image_params.setdefault(user_id, {})

    def _check_whitelist(self, interaction: discord.Interaction):
        if not whitelist_only(interaction):
            raise app_commands.CheckFailure("이 명령어는 허가된 사용자만 사용할 수 있습니다.")

    # ---------- 이미지 생성 ----------

    @app_commands.command(name="novelai_image", description="NovelAI로 이미지를 생성합니다. (허가된 사용자 전용)")
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
    async def novelai_image(
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

        used_prompt = prompt or stored.get("_last_prompt")
        if not used_prompt:
            await interaction.followup.send(
                "프롬프트를 입력하거나 먼저 한 번 이상 사용해야 합니다.", ephemeral=True
            )
            return

        used_model = model or stored.get("model", "nai-diffusion-4-5")
        used_action = action or stored.get("_last_action", "generate")

        # negative_prompt: 이번에 입력한 값이 있으면 덮어쓰고 저장, 없으면 기존값 유지
        if negative_prompt is not None:
            stored["negative_prompt"] = negative_prompt

        # API에 넘길 parameters 빌드 (내부 추적 키 제외)
        api_params = {k: v for k, v in stored.items() if k not in _INTERNAL_KEYS}

        # 사용한 값 저장
        stored["_last_prompt"] = used_prompt
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
            await interaction.followup.send(files=files)
        except Exception as e:
            await interaction.followup.send(f"에러 발생: {e}", ephemeral=True)

    # ---------- 프리셋 ----------

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
        # 내부 추적 키는 유지하고 나머지만 프리셋으로 덮어씀
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

    # ---------- 이미지 파라미터 개별 설정 ----------

    @app_commands.command(name="nai_set_model", description="이미지 모델 설정.")
    @app_commands.choices(model=[
        app_commands.Choice(name="nai-diffusion-4-5-full", value="nai-diffusion-4-5-full"),
        app_commands.Choice(name="nai-diffusion-4-5", value="nai-diffusion-4-5"),
        app_commands.Choice(name="nai-diffusion-4-5-curated", value="nai-diffusion-4-5-curated"),
        app_commands.Choice(name="nai-diffusion-4", value="nai-diffusion-4"),
        app_commands.Choice(name="nai-diffusion-4-curated-preview", value="nai-diffusion-4-curated-preview"),
        app_commands.Choice(name="nai-diffusion-3", value="nai-diffusion-3"),
    ])
    async def nai_set_model(self, interaction: discord.Interaction, model: str):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["model"] = model
        self._save_params()
        await interaction.response.send_message(f"model={model}", ephemeral=True)

    @app_commands.command(name="nai_set_width", description="이미지 width 설정.")
    async def nai_set_width(self, interaction: discord.Interaction, value: int):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["width"] = value
        self._save_params()
        await interaction.response.send_message(f"width={value}", ephemeral=True)

    @app_commands.command(name="nai_set_height", description="이미지 height 설정.")
    async def nai_set_height(self, interaction: discord.Interaction, value: int):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["height"] = value
        self._save_params()
        await interaction.response.send_message(f"height={value}", ephemeral=True)

    @app_commands.command(name="nai_set_scale", description="이미지 CFG scale 설정.")
    async def nai_set_scale(self, interaction: discord.Interaction, value: float):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["scale"] = value
        self._save_params()
        await interaction.response.send_message(f"scale={value}", ephemeral=True)

    @app_commands.command(name="nai_set_sampler", description="이미지 sampler 설정.")
    @app_commands.choices(sampler=[
        app_commands.Choice(name="k_euler_ancestral", value="k_euler_ancestral"),
        app_commands.Choice(name="k_euler", value="k_euler"),
        app_commands.Choice(name="k_dpm_2", value="k_dpm_2"),
        app_commands.Choice(name="k_dpm_2_ancestral", value="k_dpm_2_ancestral"),
        app_commands.Choice(name="k_dpmpp_2s_ancestral", value="k_dpmpp_2s_ancestral"),
        app_commands.Choice(name="k_dpmpp_2m", value="k_dpmpp_2m"),
        app_commands.Choice(name="k_dpmpp_sde", value="k_dpmpp_sde"),
        app_commands.Choice(name="ddim_v3", value="ddim_v3"),
    ])
    async def nai_set_sampler(self, interaction: discord.Interaction, sampler: str):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["sampler"] = sampler
        self._save_params()
        await interaction.response.send_message(f"sampler={sampler}", ephemeral=True)

    @app_commands.command(name="nai_set_steps", description="이미지 steps 설정.")
    async def nai_set_steps(self, interaction: discord.Interaction, value: int):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["steps"] = value
        self._save_params()
        await interaction.response.send_message(f"steps={value}", ephemeral=True)

    @app_commands.command(name="nai_set_seed", description="이미지 seed 설정.")
    async def nai_set_seed(self, interaction: discord.Interaction, value: int):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["seed"] = value
        self._save_params()
        await interaction.response.send_message(f"seed={value}", ephemeral=True)

    @app_commands.command(name="nai_set_n_samples", description="이미지 n_samples 설정.")
    async def nai_set_n_samples(self, interaction: discord.Interaction, value: int):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["n_samples"] = value
        self._save_params()
        await interaction.response.send_message(f"n_samples={value}", ephemeral=True)

    @app_commands.command(name="nai_set_negative_prompt", description="이미지 negative_prompt 설정.")
    async def nai_set_negative_prompt(self, interaction: discord.Interaction, prompt: str):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["negative_prompt"] = prompt
        self._save_params()
        await interaction.response.send_message("negative_prompt 설정됨.", ephemeral=True)

    @app_commands.command(name="nai_set_ucpreset", description="이미지 ucPreset 설정.")
    @app_commands.choices(ucpreset=[
        app_commands.Choice(name="0=Heavy", value="0"),
        app_commands.Choice(name="1=Light", value="1"),
        app_commands.Choice(name="2=None", value="2"),
    ])
    async def nai_set_ucpreset(self, interaction: discord.Interaction, ucpreset: str):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["ucPreset"] = int(ucpreset)
        self._save_params()
        await interaction.response.send_message(f"ucPreset={ucpreset}", ephemeral=True)

    @app_commands.command(name="nai_set_quality_toggle", description="이미지 qualityToggle 설정.")
    async def nai_set_quality_toggle(self, interaction: discord.Interaction, value: bool):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["qualityToggle"] = value
        self._save_params()
        await interaction.response.send_message(f"qualityToggle={value}", ephemeral=True)

    @app_commands.command(name="nai_set_noise_schedule", description="이미지 noise_schedule 설정.")
    @app_commands.choices(schedule=[
        app_commands.Choice(name="karras", value="karras"),
        app_commands.Choice(name="exponential", value="exponential"),
        app_commands.Choice(name="polyexponential", value="polyexponential"),
        app_commands.Choice(name="native", value="native"),
    ])
    async def nai_set_noise_schedule(self, interaction: discord.Interaction, schedule: str):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["noise_schedule"] = schedule
        self._save_params()
        await interaction.response.send_message(f"noise_schedule={schedule}", ephemeral=True)

    @app_commands.command(name="nai_set_cfg_rescale", description="이미지 cfg_rescale 설정.")
    async def nai_set_cfg_rescale(self, interaction: discord.Interaction, value: float):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["cfg_rescale"] = value
        self._save_params()
        await interaction.response.send_message(f"cfg_rescale={value}", ephemeral=True)

    @app_commands.command(name="nai_set_sm", description="이미지 sm (SMEA) 설정.")
    async def nai_set_sm(self, interaction: discord.Interaction, value: bool):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["sm"] = value
        self._save_params()
        await interaction.response.send_message(f"sm={value}", ephemeral=True)

    @app_commands.command(name="nai_set_sm_dyn", description="이미지 sm_dyn (SMEA DYN) 설정.")
    async def nai_set_sm_dyn(self, interaction: discord.Interaction, value: bool):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["sm_dyn"] = value
        self._save_params()
        await interaction.response.send_message(f"sm_dyn={value}", ephemeral=True)

    @app_commands.command(name="nai_set_dynamic_thresholding", description="이미지 dynamic_thresholding 설정.")
    async def nai_set_dynamic_thresholding(self, interaction: discord.Interaction, value: bool):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["dynamic_thresholding"] = value
        self._save_params()
        await interaction.response.send_message(f"dynamic_thresholding={value}", ephemeral=True)

    @app_commands.command(name="nai_set_strength", description="이미지 strength (img2img) 설정.")
    async def nai_set_strength(self, interaction: discord.Interaction, value: float):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["strength"] = value
        self._save_params()
        await interaction.response.send_message(f"strength={value}", ephemeral=True)

    @app_commands.command(name="nai_set_noise", description="이미지 noise (img2img) 설정.")
    async def nai_set_noise(self, interaction: discord.Interaction, value: float):
        self._check_whitelist(interaction)
        self._get_image_params(str(interaction.user.id))["noise"] = value
        self._save_params()
        await interaction.response.send_message(f"noise={value}", ephemeral=True)

    # ---------- 파라미터 초기화 ----------

    @app_commands.command(name="nai_clear_image_params", description="NovelAI 이미지 파라미터를 초기화합니다.")
    async def nai_clear_image_params(self, interaction: discord.Interaction):
        self._check_whitelist(interaction)
        self._image_params.pop(str(interaction.user.id), None)
        self._save_params()
        await interaction.response.send_message("이미지 파라미터가 초기화되었습니다.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(NovelAICog(bot))
