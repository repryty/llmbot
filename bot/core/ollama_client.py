import json
import logging
from typing import Any, AsyncGenerator, Optional
import openai
from bot.core.config import settings

logger = logging.getLogger(__name__)


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
        logger.info(
            "Ollama chat request base_url=%s payload=%s",
            settings.OLLAMA_BASE_URL,
            json.dumps(payload, ensure_ascii=False),
        )
        response = await self.client.chat.completions.create(**payload)
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        **params: Any,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Yields (thinking_chunk, content_chunk) pairs via streaming."""
        payload = {
            "model": model or settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            **params,
        }
        logger.info(
            "Ollama chat stream request base_url=%s payload=%s",
            settings.OLLAMA_BASE_URL,
            json.dumps(payload, ensure_ascii=False),
        )
        stream = await self.client.chat.completions.create(**payload)
        in_think = False
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            thinking = getattr(delta, "reasoning_content", None) or ""
            content = delta.content or ""

            # API가 reasoning_content를 직접 제공하면 그대로 사용
            if thinking:
                yield thinking, content or ""
                continue

            # 그렇지 않으면 content에서 <think> 태그 파싱
            if not content:
                continue

            if in_think:
                if "</think>" in content:
                    in_think = False
                    before, after = content.split("</think>", 1)
                    yield before, ""
                    if after:
                        yield "", after
                else:
                    yield content, ""
            else:
                if "<think>" in content:
                    in_think = True
                    before, after = content.split("<think>", 1)
                    if before:
                        yield "", before
                    if after:
                        if "</think>" in after:
                            in_think = False
                            thinking_part, rest = after.split("</think>", 1)
                            yield thinking_part, ""
                            if rest:
                                yield "", rest
                        else:
                            yield after, ""
                else:
                    yield "", content

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            models = await self.client.models.list()
            return [{"id": m.id, "object": m.object} for m in models.data]
        except Exception:
            return []


ollama_client = OllamaClient()
