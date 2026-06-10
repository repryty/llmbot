"""novelai-sdk 이미지 처리 유틸리티 래퍼.

novelai-sdk의 `_utils.image` 모듈은 순수 Pillow만 사용하므로
패키지 __init__.py (pydantic 의존)를 우회해 직접 로드한다.
로드 실패 시 동일한 알고리즘의 폴백 구현을 사용한다.
"""

from __future__ import annotations

import base64
import importlib.util
import logging
import sys
import types
from io import BytesIO

logger = logging.getLogger(__name__)


def _load_novelai_image_module():
    """novelai._utils.image 모듈을 패키지 init 없이 로드한다."""
    try:
        import importlib.resources as _ir

        pkg_path = None
        # 이미 로드된 경우 재사용
        if "novelai._utils.image" in sys.modules:
            return sys.modules["novelai._utils.image"]

        # novelai 패키지 경로 찾기
        nai_spec = importlib.util.find_spec("novelai")
        if nai_spec is None or nai_spec.submodule_search_locations is None:
            return None

        import pathlib

        pkg_path = pathlib.Path(list(nai_spec.submodule_search_locations)[0])
        image_py = pkg_path / "_utils" / "image.py"
        if not image_py.exists():
            return None

        # novelai 패키지를 빈 모듈로 선점해 __init__ 실행 방지
        if "novelai" not in sys.modules:
            dummy = types.ModuleType("novelai")
            sys.modules["novelai"] = dummy

        spec = importlib.util.spec_from_file_location(
            "novelai._utils.image", image_py
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["novelai._utils.image"] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        logger.warning("novelai-sdk image 모듈 로드 실패, 폴백 사용: %s", e)
        return None


_nai_mod = _load_novelai_image_module()


def image_to_base64(image_bytes: bytes) -> str:
    """이미지 bytes → base64 문자열 변환 (novelai-sdk 방식)."""
    if _nai_mod is not None:
        return _nai_mod.image_to_base64(image_bytes)
    return base64.b64encode(image_bytes).decode("utf-8")


def crop_and_resize(b64_image: str) -> str:
    """base64 이미지를 1024×1536으로 종횡비 유지하며 레터박스 패딩 (novelai-sdk 방식).

    novelai-sdk의 crop_and_resize 구현과 동일한 알고리즘이다.
    """
    if _nai_mod is not None:
        return _nai_mod.crop_and_resize(b64_image)

    # 폴백: Pillow 직접 사용 (novelai-sdk 동일 알고리즘)
    from PIL import Image as PILImage

    target_w, target_h = 1024, 1536

    img_data = base64.b64decode(b64_image)
    with BytesIO(img_data) as buf:
        image = PILImage.open(buf).convert("RGB")

    src_w, src_h = image.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_w = target_w
        new_h = int(target_w / src_ratio)
    else:
        new_h = target_h
        new_w = int(target_h * src_ratio)

    resized = image.resize((new_w, new_h), PILImage.LANCZOS)
    background = PILImage.new("RGB", (target_w, target_h), (0, 0, 0))
    background.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))

    buf = BytesIO()
    background.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
