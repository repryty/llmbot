import json
from typing import Any, Optional
import openai
from bot.core.config import settings


class OllamaClient:
    def __init__(self):
        self.client = openai.AsyncOpenAI(
            base_url=settings.OLLAMA_BASE_URL,
            api_key=settings.OLLAMA_API_KEY or "EMPTY",
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        **params: Any,
    ) -> str:
        payload = {
            "model": model or settings.OLLAMA_MODEL,
            "messages": messages,
            **params,
        }
        response = await self.client.chat.completions.create(**payload)
        return response.choices[0].message.content or ""

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            models = await self.client.models.list()
            return [{"id": m.id, "object": m.object} for m in models.data]
        except Exception:
            return []


ollama_client = OllamaClient()
