"""중앙 로깅 모듈.

- 로그 파일: data/bot.log (최대 5 MB, 백업 2개 → 최대 15 MB)
- API 전용 로거: logging.getLogger("api.request")
- 헬퍼: log_api_request(), get_recent_logs()
"""

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── 경로 설정 ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent.parent  # 프로젝트 루트
LOG_DIR = _ROOT / "data"
LOG_FILE = LOG_DIR / "bot.log"

MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 2              # bot.log.1, bot.log.2 까지 보관

# ── 포매터 ───────────────────────────────────────────────────────────────────
_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """루트 로거에 파일(DEBUG+) / 콘솔(ERROR+) 핸들러를 설정한다.

    main.py 맨 앞에서 한 번만 호출하면 된다.
    이미 핸들러가 등록된 경우(중복 호출 방지) 조용히 건너뛴다.
    """
    root = logging.getLogger()

    # 중복 호출 방지: RotatingFileHandler 가 이미 있으면 스킵
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(fmt=_FMT, datefmt=_DATEFMT)

    # 파일 핸들러 – DEBUG 이상 기록, 5 MB 초과 시 자동 회전
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # 콘솔 핸들러 – ERROR 이상만 출력
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(formatter)

    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


# ── API 요청 로거 ─────────────────────────────────────────────────────────────
_api_logger = logging.getLogger("api.request")


def _mask(data: dict, keys: list[str]) -> dict:
    """민감 키(예: api_key, Authorization) 를 마스킹한 사본을 반환한다."""
    out = dict(data)
    for k in keys:
        if k in out:
            out[k] = "***"
    return out


def log_api_request(
    service: str,
    method: str,
    endpoint: str,
    payload: dict,
    *,
    mask_keys: list[str] | None = None,
) -> None:
    """외부 API로 나가는 요청을 구조화된 형태로 기록한다.

    Args:
        service:   서비스 이름 ("ollama", "novelai", …)
        method:    HTTP 메서드 ("POST", "GET", …)
        endpoint:  요청 URL 또는 경로
        payload:   전송할 전체 페이로드 딕셔너리
        mask_keys: 로그에서 마스킹할 키 목록
    """
    safe = _mask(payload, mask_keys or [])
    _api_logger.info(
        "[API REQUEST] service=%s method=%s endpoint=%s\n%s",
        service,
        method,
        endpoint,
        json.dumps(safe, ensure_ascii=False, indent=2, default=str),
    )


# ── 로그 조회 헬퍼 ────────────────────────────────────────────────────────────

def get_recent_logs(n_lines: int = 100) -> str:
    """로그 파일의 마지막 n_lines 줄을 반환한다."""
    if not LOG_FILE.exists():
        return "(로그 파일이 없습니다)"

    with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if not lines:
        return "(로그가 비어있습니다)"

    return "".join(lines[-n_lines:]).strip()


def get_log_size_info() -> dict:
    """로그 파일 크기 정보를 딕셔너리로 반환한다."""
    if not LOG_FILE.exists():
        return {"exists": False, "bytes": 0, "kb": 0.0, "mb": 0.0}

    size = LOG_FILE.stat().st_size
    return {
        "exists": True,
        "bytes": size,
        "kb": size / 1024,
        "mb": size / 1024 / 1024,
        "path": str(LOG_FILE),
        "max_mb": MAX_BYTES / 1024 / 1024,
    }
