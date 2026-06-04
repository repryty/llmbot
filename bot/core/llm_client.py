import logging
from typing import Any, AsyncGenerator, Optional
import openai
from bot.core.config import settings
from bot.core.bot_logger import log_api_request

logger = logging.getLogger(__name__)

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _resolve_gemini(model: Optional[str], params: dict) -> bool:
    """is_gemini 파라미터 우선, 없으면 모델명에 'gemini' 포함 여부로 자동 판단."""
    override = params.get("is_gemini")
    if override is not None:
        return bool(override)
    return bool(model and "gemini" in model.lower())


class LLMClient:
    def __init__(self):
        self._openai = openai.AsyncOpenAI(
            base_url=settings.OPENAI_BASE_URL,
            api_key=settings.OPENAI_API_KEY or "EMPTY",
        )
        self._gemini = openai.AsyncOpenAI(
            base_url=_GEMINI_BASE_URL,
            api_key=settings.GEMINI_API_KEY or "EMPTY",
        )

    def _pick(self, model: Optional[str], params: dict) -> tuple[openai.AsyncOpenAI, str, str, bool]:
        """(client, resolved_model, log_endpoint, is_gemini) 반환. params에서 is_gemini 제거."""
        use_gemini = _resolve_gemini(model, params)
        params.pop("is_gemini", None)
        if use_gemini:
            m = model or settings.GEMINI_MODEL
            return self._gemini, m, f"{_GEMINI_BASE_URL}chat/completions", True
        else:
            m = model or settings.OPENAI_MODEL
            return self._openai, m, f"{settings.OPENAI_BASE_URL}/chat/completions", False

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        **params: Any,
    ) -> str:
        client, resolved, endpoint, use_gemini = self._pick(model, params)
        payload: dict[str, Any] = {"model": resolved, "messages": messages, **params}
        if use_gemini:
            payload["service_tier"] = "flex"
        log_api_request(service="gemini" if use_gemini else "openai", method="POST",
                        endpoint=endpoint, payload=payload)
        response = await client.chat.completions.create(**payload)
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        **params: Any,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Yields (thinking_chunk, content_chunk) pairs via streaming."""
        client, resolved, endpoint, use_gemini = self._pick(model, params)
        payload: dict[str, Any] = {"model": resolved, "messages": messages, "stream": True, **params}
        if use_gemini:
            payload["service_tier"] = "flex"
        log_api_request(service="gemini" if use_gemini else "openai", method="POST",
                        endpoint=endpoint, payload=payload)
        stream = await client.chat.completions.create(**payload)
        in_think = False
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            thinking = getattr(delta, "reasoning_content", None) or ""
            content = delta.content or ""

            if thinking:
                yield thinking, content or ""
                continue

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

    async def list_models(self, use_gemini: bool = False) -> list[dict[str, Any]]:
        client = self._gemini if use_gemini else self._openai
        try:
            models = await client.models.list()
            return [{"id": m.id, "object": m.object} for m in models.data]
        except Exception:
            return []


llm_client = LLMClient()
