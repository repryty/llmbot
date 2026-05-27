"""중앙 로깅 모듈.

파일: data/bot.log (최대 5 MB, 백업 2개)

모드 전환
---------
- 일반 모드(기본): api.request 로거 레코드만 파일에 기록
                   → Ollama / NovelAI 호출 내역만 저장
- 디버그 모드     : 모든 레코드(discord.*, bot.* 포함) 파일에 기록

set_debug_mode(True/False) 또는 환경변수 LOG_DEBUG=true 로 제어.
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

# ── 디버그 모드 상태 ──────────────────────────────────────────────────────────
_debug_mode: bool = os.getenv("LOG_DEBUG", "").lower() in ("1", "true", "yes")


def is_debug_mode() -> bool:
    """현재 디버그 모드 여부를 반환한다."""
    return _debug_mode


def set_debug_mode(enabled: bool) -> None:
    """런타임에 디버그 모드를 전환한다.

    True  → 모든 로그 파일에 기록
    False → api.request 로그만 파일에 기록
    """
    global _debug_mode
    _debug_mode = enabled


# ── 파일 핸들러 필터 ──────────────────────────────────────────────────────────

class _ApiOrDebugFilter(logging.Filter):
    """파일 핸들러에 붙는 필터.

    - 일반 모드: 로거 이름이 'api.' 로 시작하는 레코드만 통과
    - 디버그 모드: 모든 레코드 통과
    """
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if _debug_mode:
            return True
        return record.name.startswith("api.")


# ── 초기화 ───────────────────────────────────────────────────────────────────

def setup_logging(debug: bool | None = None) -> None:
    """루트 로거에 파일 / 콘솔 핸들러를 설정한다.

    Args:
        debug: True/False 로 초기 디버그 모드를 지정.
               None 이면 환경변수 LOG_DEBUG 값(모듈 로드 시 결정) 을 사용.
    """
    global _debug_mode
    if debug is not None:
        _debug_mode = debug

    root = logging.getLogger()

    # 중복 호출 방지
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(fmt=_FMT, datefmt=_DATEFMT)

    # 파일 핸들러 – api.request(또는 디버그 모드 시 전체) 기록, 5 MB 회전
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_ApiOrDebugFilter())

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
    """민감 키를 마스킹한 사본을 반환한다."""
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
    """외부 API로 나가는 요청을 구조화된 형태로 기록한다."""
    safe = _mask(payload, mask_keys or [])
    _api_logger.info(
        "[API REQUEST] service=%s method=%s endpoint=%s\n%s",
        service,
        method,
        endpoint,
        json.dumps(safe, ensure_ascii=False, indent=2, default=str),
    )


# ── 로그 조회 헬퍼 ────────────────────────────────────────────────────────────

def get_recent_logs(n_lines: int = 2) -> str:
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
