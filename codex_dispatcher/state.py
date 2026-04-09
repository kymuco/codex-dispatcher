from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _default_thread() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "session_id": None,
        "last_account": None,
        "model": None,
        "reasoning_effort": None,
        "sandbox_mode": None,
        "created_at": now,
        "updated_at": now,
    }


def _default_chat() -> dict[str, Any]:
    return {
        "active_alias": "main",
        "threads": {
            "main": _default_thread(),
        },
    }


def _default_state() -> dict[str, Any]:
    return {
        "active_account": None,
        "chats": {},
    }


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if self.path.exists():
            self._state = self._load_from_disk()
        else:
            self._state = _default_state()
            self._save_to_disk()

    def _load_from_disk(self) -> dict[str, Any]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid state file: {self.path}")
        state = _default_state()
        state.update(raw)
        return state

    def _save_to_disk(self) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def get_active_account(self) -> str | None:
        with self._lock:
            return self._state.get("active_account")

    def set_active_account(self, name: str) -> None:
        with self._lock:
            self._state["active_account"] = name
            self._save_to_disk()

    def ensure_chat(self, chat_id: int) -> dict[str, Any]:
        with self._lock:
            key = str(chat_id)
            chats = self._state["chats"]
            chat = chats.get(key)
            if not isinstance(chat, dict):
                chat = _default_chat()
                chats[key] = chat
                self._save_to_disk()
            return deepcopy(chat)

    def _mutate_chat(self, chat_id: int) -> dict[str, Any]:
        key = str(chat_id)
        chats = self._state["chats"]
        chat = chats.get(key)
        if not isinstance(chat, dict):
            chat = _default_chat()
            chats[key] = chat
        return chat

    def list_threads(self, chat_id: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
        with self._lock:
            chat = self._mutate_chat(chat_id)
            active_alias = str(chat.get("active_alias", "main"))
            threads = deepcopy(chat.get("threads", {}))
            self._save_to_disk()
            return active_alias, deepcopy(chat), threads

    def create_or_select_thread(self, chat_id: int, alias: str) -> dict[str, Any]:
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias must not be empty.")
        with self._lock:
            chat, thread = self._ensure_thread(chat_id, alias)
            chat["active_alias"] = alias
            thread["updated_at"] = utc_now_iso()
            self._save_to_disk()
            return deepcopy(thread)

    def set_active_alias(self, chat_id: int, alias: str) -> dict[str, Any]:
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias must not be empty.")
        with self._lock:
            chat = self._mutate_chat(chat_id)
            threads = chat.setdefault("threads", {})
            thread = threads.get(alias)
            if not isinstance(thread, dict):
                raise KeyError(alias)
            chat["active_alias"] = alias
            thread["updated_at"] = utc_now_iso()
            self._save_to_disk()
            return deepcopy(thread)

    def get_active_thread(self, chat_id: int) -> tuple[str, dict[str, Any]]:
        with self._lock:
            chat = self._mutate_chat(chat_id)
            active_alias = str(chat.get("active_alias", "main"))
            _, thread = self._ensure_thread(chat_id, active_alias)
            self._save_to_disk()
            return active_alias, deepcopy(thread)

    def get_thread(self, chat_id: int, alias: str) -> dict[str, Any]:
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias must not be empty.")
        with self._lock:
            _, thread = self._ensure_thread(chat_id, alias)
            self._save_to_disk()
            return deepcopy(thread)

    def update_thread(
        self,
        chat_id: int,
        alias: str,
        *,
        session_id: str | None,
        account_name: str | None = None,
    ) -> dict[str, Any]:
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias must not be empty.")
        with self._lock:
            chat, thread = self._ensure_thread(chat_id, alias)
            thread["session_id"] = session_id
            thread["last_account"] = account_name
            thread["updated_at"] = utc_now_iso()
            chat["active_alias"] = alias
            self._save_to_disk()
            return deepcopy(thread)

    def reset_thread(self, chat_id: int, alias: str) -> dict[str, Any]:
        return self.update_thread(chat_id, alias, session_id=None, account_name=None)

    def set_thread_model(self, chat_id: int, alias: str, model: str | None) -> dict[str, Any]:
        return self._set_thread_setting(chat_id, alias, "model", model)

    def set_thread_reasoning_effort(
        self,
        chat_id: int,
        alias: str,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        return self._set_thread_setting(chat_id, alias, "reasoning_effort", reasoning_effort)

    def set_thread_sandbox_mode(self, chat_id: int, alias: str, sandbox_mode: str | None) -> dict[str, Any]:
        return self._set_thread_setting(chat_id, alias, "sandbox_mode", sandbox_mode)

    def _ensure_thread(self, chat_id: int, alias: str) -> tuple[dict[str, Any], dict[str, Any]]:
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias must not be empty.")
        chat = self._mutate_chat(chat_id)
        threads = chat.setdefault("threads", {})
        thread = threads.get(alias)
        if not isinstance(thread, dict):
            thread = _default_thread()
            threads[alias] = thread
        return chat, thread

    def _set_thread_setting(
        self,
        chat_id: int,
        alias: str,
        field: str,
        value: str | None,
    ) -> dict[str, Any]:
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias must not be empty.")
        with self._lock:
            chat, thread = self._ensure_thread(chat_id, alias)
            thread[field] = value
            thread["updated_at"] = utc_now_iso()
            chat["active_alias"] = alias
            self._save_to_disk()
            return deepcopy(thread)
