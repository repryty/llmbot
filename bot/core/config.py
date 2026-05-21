from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DISCORD_TOKEN: str

    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "llama3"
    OLLAMA_API_KEY: Optional[str] = None

    NOVELAI_BASE_URL: str = "https://api.novelai.net"
    NOVELAI_API_KEY: Optional[str] = None
    WHITELIST: str = ""

    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_TOP_P: float = 0.9
    DEFAULT_MAX_TOKENS: int = 2048

    @property
    def whitelist_ids(self) -> set[int]:
        if not self.WHITELIST:
            return set()
        return {int(x.strip()) for x in self.WHITELIST.split(",") if x.strip().isdigit()}


settings = Settings()
