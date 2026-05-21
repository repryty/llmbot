from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    messages: list[dict[str, str]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    system_prompt: str | None = None

    def reset(self):
        self.messages = []
        self.params = {}
        self.system_prompt = None

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def delete_message(self, index: int):
        if 0 <= index < len(self.messages):
            self.messages.pop(index)
            return True
        return False

    def get_messages(self) -> list[dict[str, str]]:
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.messages)
        return msgs

    def update_params(self, **kwargs):
        for k, v in kwargs.items():
            if v is not None:
                self.params[k] = v

    def remove_param(self, key: str):
        self.params.pop(key, None)

    def clear_params(self):
        self.params = {}
