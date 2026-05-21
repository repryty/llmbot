import json
import io
import zipfile
from typing import Any, Optional
from urllib.parse import urlparse
import httpx
from bot.core.config import settings

_V4_MODELS = {
    "nai-diffusion-4",
    "nai-diffusion-4-curated-preview",
    "nai-diffusion-4-full",
    "nai-diffusion-4-5",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-5-full",
}


def _is_v4(model: str) -> bool:
    return model in _V4_MODELS


def _inject_v4_params(input_text: str, params: dict) -> dict:
    """V4+ 모델에 필요한 파라미터를 자동으로 채운다."""
    p = dict(params)
    negative = p.get("negative_prompt", "")
    seed = p.get("seed", 0)
    sampler = p.get("sampler", "k_euler_ancestral")
    noise_schedule = p.get("noise_schedule", "karras")

    p.setdefault("params_version", 1)
    p.setdefault("legacy", False)
    p.setdefault("legacy_v3_extend", False)
    p.setdefault("add_original_image", False)
    p.setdefault("controlnet_strength", 1.0)
    p.setdefault("uncond_scale", 1.0)
    p.setdefault("reference_image_multiple", [])
    p.setdefault("reference_information_extracted_multiple", [])
    p.setdefault("reference_strength_multiple", [])
    p["extra_noise_seed"] = seed
    p["prompt"] = input_text

    p["v4_prompt"] = {
        "use_coords": False,
        "use_order": False,
        "caption": {"base_caption": input_text, "char_captions": []},
    }
    p["v4_negative_prompt"] = {
        "use_coords": False,
        "use_order": False,
        "caption": {"base_caption": negative, "char_captions": []},
    }

    # k_euler_ancestral + non-native 스케줄러 조합 시 필요한 플래그
    if sampler == "k_euler_ancestral" and noise_schedule != "native":
        p.setdefault("deliberate_euler_ancestral_bug", False)
        p.setdefault("prefer_brownian", True)

    return p


class NovelAIClient:
    def __init__(self):
        parsed = urlparse(settings.NOVELAI_BASE_URL)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.api_key = settings.NOVELAI_API_KEY or ""
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate_text(
        self,
        input_text: str,
        model: str = "kayra-v1",
        params: Optional[dict[str, Any]] = None,
    ) -> str:
        url = f"{self.base_url}/ai/generate-stream"
        payload = {
            "input": input_text,
            "model": model,
            "parameters": params or {},
        }
        chunks = []
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=payload, headers=self.headers, timeout=120.0) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            if "output" in obj:
                                chunks.append(obj["output"])
                        except json.JSONDecodeError:
                            continue
        if not chunks:
            return ""
        return chunks[-1]

    async def generate_image(
        self,
        input_text: str,
        model: str = "nai-diffusion-4-5",
        action: str = "generate",
        params: Optional[dict[str, Any]] = None,
    ) -> list[bytes]:
        url = f"{self.base_url}/ai/generate-image"
        parameters = dict(params or {})

        if _is_v4(model):
            parameters = _inject_v4_params(input_text, parameters)

        payload = {
            "input": input_text,
            "model": model,
            "action": action,
            "parameters": parameters,
        }
        images = []
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self.headers, timeout=120.0)
            if not resp.is_success:
                raise Exception(f"HTTP {resp.status_code} {resp.reason_phrase}: {resp.text[:500]}")
            content = resp.content
            if content[:4] == b"PK\x03\x04":
                z = zipfile.ZipFile(io.BytesIO(content))
                for name in z.namelist():
                    images.append(z.read(name))
            else:
                images.append(content)
        return images

    async def upscale_image(self, image_bytes: bytes, width: int = 0, height: int = 0) -> bytes:
        return b""


novelai_client = NovelAIClient()
