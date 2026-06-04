import json
from typing import Any

from bot.core.agent_tools import (
    get_member_info,
    list_channels,
    python_exec,
    read_history,
    read_memo,
    save_memo,
)

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "python_exec",
            "description": "Python 코드를 실행하고 stdout/stderr 결과를 반환합니다. 계산, 데이터 처리, 문자열 조작 등에 활용하세요.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "실행할 Python 코드"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_history",
            "description": "현재 Discord 채널의 최근 메시지를 읽어 대화 흐름과 컨텍스트를 파악합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "읽을 메시지 수 (1~50, 기본값 20)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_member_info",
            "description": "Discord 서버 멤버의 닉네임, 역할, 가입일 정보를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_id": {
                        "type": "string",
                        "description": "멤버의 표시 이름(닉네임) 또는 Discord 사용자 ID",
                    },
                },
                "required": ["name_or_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_channels",
            "description": "Discord 서버의 텍스트 채널 목록과 각 채널의 토픽을 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memo",
            "description": "사용자 개인 메모를 영구 저장합니다. 세션을 초기화해도 유지됩니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "메모 이름(키)"},
                    "content": {"type": "string", "description": "메모 내용"},
                },
                "required": ["key", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_memo",
            "description": "저장된 개인 메모를 읽습니다. key에 '*'을 전달하면 전체 목록을 반환합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "메모 이름(키). '*'이면 전체 조회",
                    },
                },
                "required": ["key"],
            },
        },
    },
]


class ToolDispatcher:
    def __init__(self, user_id: str, channel=None, guild=None):
        self.user_id = user_id
        self.channel = channel
        self.guild = guild

    async def dispatch(self, name: str, arguments: str) -> str:
        try:
            args: dict = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"인수 파싱 오류: {arguments!r}"

        try:
            match name:
                case "python_exec":
                    return await python_exec(args["code"])
                case "read_history":
                    if self.channel is None:
                        return "채널 컨텍스트 없음 (DM 또는 슬래시 커맨드에서는 사용 불가)"
                    return await read_history(self.channel, args.get("limit", 20))
                case "get_member_info":
                    if self.guild is None:
                        return "서버 컨텍스트 없음 (DM에서는 사용 불가)"
                    return await get_member_info(self.guild, args["name_or_id"])
                case "list_channels":
                    if self.guild is None:
                        return "서버 컨텍스트 없음 (DM에서는 사용 불가)"
                    return await list_channels(self.guild)
                case "save_memo":
                    return save_memo(self.user_id, args["key"], args["content"])
                case "read_memo":
                    return read_memo(self.user_id, args["key"])
                case _:
                    return f"알 수 없는 툴: {name}"
        except KeyError as e:
            return f"필수 인수 누락: {e}"
        except Exception as e:
            return f"툴 실행 오류: {e}"
