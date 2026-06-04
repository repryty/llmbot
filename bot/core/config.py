from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DISCORD_TOKEN: str

    # OpenAI-Compatible API (범용)
    OPENAI_BASE_URL: str = "http://localhost/v1"
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_API_KEY: Optional[str] = None

    # Gemini (google-genai 라이브러리 직접 사용)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    NOVELAI_BASE_URL: str = "https://api.novelai.net"
    NOVELAI_API_KEY: Optional[str] = None
    WHITELIST: str = ""

    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_TOP_P: float = 0.9
    DEFAULT_MAX_TOKENS: int = 2048

    # 로깅: True 이면 모든 로그 저장, False(기본) 이면 API 호출 로그만 저장
    LOG_DEBUG: bool = False

    @property
    def whitelist_ids(self) -> set[int]:
        if not self.WHITELIST:
            return set()
        return {int(x.strip()) for x in self.WHITELIST.split(",") if x.strip().isdigit()}


settings = Settings()
