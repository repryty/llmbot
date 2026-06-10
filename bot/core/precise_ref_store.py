"""Precise Reference 저장소 — 사용자별 레퍼런스 데이터 로드/빌드."""

import json
from pathlib import Path

PRECISE_REFS_PATH = Path("data/precise_refs.json")

_V4_5_MODELS = {
    "nai-diffusion-4-5",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-5-full",
}


def load_user_refs(user_id: str) -> list[dict]:
    """사용자의 Precise Reference 목록을 반환."""
    if not PRECISE_REFS_PATH.exists():
        return []
    try:
        data = json.loads(PRECISE_REFS_PATH.read_text(encoding="utf-8"))
        return data.get(user_id, [])
    except Exception:
        return []


def build_director_params(refs: list[dict]) -> dict:
    """레퍼런스 목록에서 NAI API director_reference_* 파라미터를 생성한다."""
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


def get_precise_ref_params(
    user_id: str, model: str, ignore_precise: bool = False
) -> dict:
    """저장된 Precise Reference API 파라미터를 반환한다.

    V4.5 모델이 아니거나, 레퍼런스가 없거나, ignore_precise=True면 빈 dict 반환.
    """
    if ignore_precise or model not in _V4_5_MODELS:
        return {}
    refs = load_user_refs(user_id)
    return build_director_params(refs) if refs else {}
