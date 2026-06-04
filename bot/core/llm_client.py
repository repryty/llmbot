import json
import logging
from typing import Any, AsyncGenerator, Optional
import openai
from bot.core.config import settings
from bot.core.bot_logger import log_api_request

logger = logging.getLogger(__name__)


# ── Gemini native response wrappers ─────────────────────────────────────────
# chat_raw이 OpenAI와 동일한 인터페이스를 반환하도록 래핑

class _FuncCall:
    __slots__ = ("name", "arguments")

    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    __slots__ = ("id", "type", "function")

    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.type = "function"
        self.function = _FuncCall(name, arguments)


class _Message:
    __slots__ = ("content", "tool_calls")

    def __init__(self, content: str | None, tool_calls: list | None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    __slots__ = ("message",)

    def __init__(self, message: _Message):
        self.message = message


class _GeminiResponse:
    __slots__ = ("choices",)

    def __init__(self, choices: list[_Choice]):
        self.choices = choices


# ── Gemini native client ─────────────────────────────────────────────────────

class _GeminiClient:
    def __init__(self):
        from google import genai  # lazy import — google-genai 미설치 시 오류 지연
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY or "")

    # ── 메시지 변환 ────────────────────────────────────────────────────────────

    @staticmethod
    def _to_contents(messages: list[dict]) -> tuple[str | None, list]:
        """OpenAI 형식 messages → (system_instruction, Gemini contents)"""
        id_to_name: dict[str, str] = {}
        for msg in messages:
            for tc in msg.get("tool_calls") or []:
                id_to_name[tc["id"]] = tc["function"]["name"]

        system_instruction: str | None = None
        contents: list[dict] = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system_instruction = msg.get("content") or ""

            elif role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": msg.get("content") or ""}],
                })

            elif role == "assistant":
                parts: list[dict] = []
                if msg.get("content"):
                    parts.append({"text": msg["content"]})
                for tc in msg.get("tool_calls") or []:
                    raw = tc["function"]["arguments"]
                    args = json.loads(raw) if isinstance(raw, str) else raw
                    parts.append({"function_call": {"name": tc["function"]["name"], "args": args}})
                if parts:
                    contents.append({"role": "model", "parts": parts})

            elif role == "tool":
                func_name = id_to_name.get(msg.get("tool_call_id", ""), "unknown")
                contents.append({
                    "role": "user",
                    "parts": [{"function_response": {
                        "name": func_name,
                        "response": {"result": msg.get("content") or ""},
                    }}],
                })

        return system_instruction, contents

    @staticmethod
    def _schema_upper(schema: dict) -> dict:
        """JSON Schema 타입명을 Gemini 요구사항에 맞게 대문자로 변환."""
        result: dict[str, Any] = {}
        if "type" in schema:
            result["type"] = schema["type"].upper()
        if "description" in schema:
            result["description"] = schema["description"]
        if "properties" in schema:
            result["properties"] = {
                k: _GeminiClient._schema_upper(v)
                for k, v in schema["properties"].items()
            }
        if "required" in schema:
            result["required"] = schema["required"]
        if "items" in schema:
            result["items"] = _GeminiClient._schema_upper(schema["items"])
        return result

    @classmethod
    def _to_gemini_tools(cls, tools: list[dict]) -> list[dict]:
        decls = []
        for t in tools:
            if t.get("type") != "function":
                continue
            f = t["function"]
            decl: dict[str, Any] = {
                "name": f["name"],
                "description": f.get("description", ""),
            }
            if "parameters" in f:
                decl["parameters"] = cls._schema_upper(f["parameters"])
            decls.append(decl)
        return [{"function_declarations": decls}]

    def _make_config(
        self,
        system_instruction: str | None,
        params: dict,
        tools: list[dict] | None = None,
    ):
        from google.genai import types

        kwargs: dict[str, Any] = {}
        if system_instruction:
            kwargs["system_instruction"] = system_instruction

        temp = params.pop("temperature", None)
        top_p = params.pop("top_p", None)
        max_tokens = params.pop("max_tokens", None)
        stop = params.pop("stop", None)
        # OpenAI 전용 파라미터 제거
        for k in ["seed", "presence_penalty", "frequency_penalty", "n", "response_format"]:
            params.pop(k, None)

        if temp is not None:
            kwargs["temperature"] = temp
        if top_p is not None:
            kwargs["top_p"] = top_p
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        if stop is not None:
            kwargs["stop_sequences"] = [stop] if isinstance(stop, str) else stop
        if tools:
            kwargs["tools"] = self._to_gemini_tools(tools)

        return types.GenerateContentConfig(**kwargs)

    # ── API 메서드 ─────────────────────────────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        **params,
    ) -> AsyncGenerator[tuple[str, str], None]:
        system_instruction, contents = self._to_contents(messages)
        params.pop("tools", None)
        config = self._make_config(system_instruction, params)
        resolved = model or settings.GEMINI_MODEL
        log_api_request(
            "gemini-native", "POST", f"models/{resolved}:streamGenerateContent",
            {"model": resolved, "turns": len(contents)},
        )
        async for chunk in await self._client.aio.models.generate_content_stream(
            model=resolved, contents=contents, config=config,
        ):
            if not chunk.candidates:
                continue
            cand = chunk.candidates[0]
            if not cand.content or not cand.content.parts:
                continue
            for part in cand.content.parts:
                if getattr(part, "thought", False):
                    if part.text:
                        yield part.text, ""
                elif part.text:
                    yield "", part.text

    async def chat_raw(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        **params,
    ) -> _GeminiResponse:
        system_instruction, contents = self._to_contents(messages)
        tools = params.pop("tools", None)
        config = self._make_config(system_instruction, params, tools)
        resolved = model or settings.GEMINI_MODEL
        log_api_request(
            "gemini-native", "POST", f"models/{resolved}:generateContent",
            {"model": resolved, "turns": len(contents), "has_tools": bool(tools)},
        )
        response = await self._client.aio.models.generate_content(
            model=resolved, contents=contents, config=config,
        )
        if not response.candidates:
            return _GeminiResponse([_Choice(_Message(None, None))])

        text_parts: list[str] = []
        tool_calls: list[_ToolCall] = []
        for i, part in enumerate(response.candidates[0].content.parts):
            if getattr(part, "thought", False):
                continue
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(_ToolCall(
                    call_id=f"call_{i}",
                    name=fc.name,
                    arguments=json.dumps(dict(fc.args)),
                ))
            elif part.text:
                text_parts.append(part.text)

        return _GeminiResponse([_Choice(_Message(
            "".join(text_parts) or None,
            tool_calls or None,
        ))])

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            result = []
            async for m in await self._client.aio.models.list():
                result.append({"id": m.name, "object": "model"})
            return result
        except Exception:
            return []


# ── LLMClient ─────────────────────────────────────────────────────────────────

class LLMClient:
    def __init__(self):
        self._openai = openai.AsyncOpenAI(
            base_url=settings.OPENAI_BASE_URL,
            api_key=settings.OPENAI_API_KEY or "EMPTY",
        )
        self.__gemini: _GeminiClient | None = None

    @property
    def _gemini(self) -> _GeminiClient:
        if self.__gemini is None:
            self.__gemini = _GeminiClient()
        return self.__gemini

    def _pop_gemini_flag(self, model: Optional[str], params: dict) -> tuple[bool, Optional[str]]:
        """(use_gemini, model) 반환. params에서 is_gemini 제거."""
        override = params.pop("is_gemini", None)
        if override is not None:
            return bool(override), model
        return bool(model and "gemini" in model.lower()), model

    async def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        **params: Any,
    ) -> AsyncGenerator[tuple[str, str], None]:
        use_gemini, model = self._pop_gemini_flag(model, params)

        if use_gemini:
            async for t, c in self._gemini.chat_stream(messages, model, **params):
                yield t, c
            return

        # OpenAI-compatible 스트리밍
        payload: dict[str, Any] = {
            "model": model or settings.OPENAI_MODEL,
            "messages": messages,
            "stream": True,
            **params,
        }
        log_api_request("openai", "POST", f"{settings.OPENAI_BASE_URL}/chat/completions", payload)
        stream = await self._openai.chat.completions.create(**payload)
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

    async def chat_raw(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        **params: Any,
    ):
        """tool_calls 검사용 non-streaming 응답. Gemini/OpenAI 모두 동일 인터페이스."""
        use_gemini, model = self._pop_gemini_flag(model, params)

        if use_gemini:
            return await self._gemini.chat_raw(messages, model, **params)

        payload: dict[str, Any] = {
            "model": model or settings.OPENAI_MODEL,
            "messages": messages,
            **params,
        }
        log_api_request("openai", "POST", f"{settings.OPENAI_BASE_URL}/chat/completions", payload)
        return await self._openai.chat.completions.create(**payload)

    async def list_models(self, use_gemini: bool = False) -> list[dict[str, Any]]:
        if use_gemini:
            return await self._gemini.list_models()
        try:
            models = await self._openai.models.list()
            return [{"id": m.id, "object": m.object} for m in models.data]
        except Exception:
            return []


llm_client = LLMClient()
