import json
from pathlib import Path
from typing import Any
from bot.models.session import Session

SESSIONS_PATH = Path("data/chat_sessions.json")
DEFAULT_PROMPT_PATH = Path("prompts/system_prompt.txt")


class SessionManager:
    def __init__(self):
        self._default_system_prompt: str | None = None
        if DEFAULT_PROMPT_PATH.exists():
            self._default_system_prompt = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8").strip() or None
        self._sessions: dict[str, Session] = self._load()

    def _load(self) -> dict[str, Session]:
        if not SESSIONS_PATH.exists():
            return {}
        try:
            raw = json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
            return {
                uid: Session(
                    messages=data.get("messages", []),
                    params=data.get("params", {}),
                    system_prompt=data.get("system_prompt"),
                )
                for uid, data in raw.items()
            }
        except Exception:
            return {}

    def _save(self):
        SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            uid: {
                "messages": s.messages,
                "params": s.params,
                "system_prompt": s.system_prompt,
            }
            for uid, s in self._sessions.items()
        }
        SESSIONS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, user_id: str) -> Session:
        if user_id not in self._sessions:
            self._sessions[user_id] = Session(system_prompt=self._default_system_prompt)
        return self._sessions[user_id]

    def reset(self, user_id: str):
        self.get(user_id).reset()
        self._save()

    def add_message(self, user_id: str, role: str, content: str):
        self.get(user_id).add_message(role, content)
        self._save()

    def delete_message(self, user_id: str, index: int) -> bool:
        result = self.get(user_id).delete_message(index - 1)
        if result:
            self._save()
        return result

    def set_system_prompt(self, user_id: str, prompt: str | None):
        self.get(user_id).system_prompt = prompt
        self._save()

    def update_params(self, user_id: str, **kwargs):
        self.get(user_id).update_params(**kwargs)
        self._save()

    def remove_param(self, user_id: str, key: str):
        self.get(user_id).remove_param(key)
        self._save()

    def clear_params(self, user_id: str):
        self.get(user_id).clear_params()
        self._save()

    def get_messages(self, user_id: str) -> list[dict[str, str]]:
        return self.get(user_id).get_messages()

    def get_params(self, user_id: str) -> dict[str, Any]:
        return dict(self.get(user_id).params)


session_manager = SessionManager()
