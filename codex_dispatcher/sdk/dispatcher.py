from __future__ import annotations

from pathlib import Path
from typing import Any

from ..check_env import run_environment_check
from ..codex_runner import CodexRunResult
from ..config import AppConfig, load_config
from ..core import (
    AccountEntry,
    DispatcherService,
    HealthSnapshot,
    SessionIdSnapshot,
    SettingsSnapshot,
    StatusSnapshot,
    ThreadsSnapshot,
)
from ..session_manager import SessionAttachment, SessionClone, SessionExport


class Dispatcher:
    """Python facade over dispatcher orchestration services."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._service = DispatcherService(config)

    @classmethod
    def from_config(cls, config_path: str | Path | None = None) -> Dispatcher:
        raw_path: str | None
        if isinstance(config_path, Path):
            raw_path = str(config_path)
        else:
            raw_path = config_path
        return cls(load_config(raw_path))

    @property
    def config(self) -> AppConfig:
        return self._config

    def check(self) -> tuple[int, str]:
        return run_environment_check(self._config)

    def startup_report(self) -> dict[str, Any]:
        return self._service.startup_report()

    def ensure_ready(self) -> None:
        self._service.run_startup_checks()

    def accounts(self) -> tuple[AccountEntry, ...]:
        return self._service.get_accounts()

    def switch_account(self, name: str) -> None:
        self._service.switch_account(name)

    def active_chat(self, chat_id: int) -> str:
        return self._service.get_active_alias(chat_id)

    def new_chat(self, chat_id: int, alias: str) -> str:
        normalized = alias.strip()
        if not normalized:
            raise ValueError("Local chat alias must not be empty.")
        return self._service.create_or_select_chat(chat_id, normalized)

    def use_chat(self, chat_id: int, alias: str) -> None:
        self._service.use_chat(chat_id, alias)

    def reset_chat(self, chat_id: int, alias: str | None = None) -> str:
        target_alias = alias or self._service.get_active_alias(chat_id)
        self._service.reset_chat(chat_id, target_alias)
        return target_alias

    def status(self, chat_id: int) -> StatusSnapshot:
        return self._service.get_status(chat_id)

    def health(self, chat_id: int) -> HealthSnapshot:
        return self._service.get_health(chat_id)

    def threads(self, chat_id: int) -> ThreadsSnapshot:
        return self._service.list_threads(chat_id)

    def settings(self, chat_id: int) -> SettingsSnapshot:
        return self._service.get_settings(chat_id)

    def session_id(self, chat_id: int) -> SessionIdSnapshot:
        return self._service.get_session_id(chat_id)

    def set_model(self, chat_id: int, model: str | None, *, alias: str | None = None) -> None:
        target_alias = alias or self._service.get_active_alias(chat_id)
        self._service.set_model(chat_id, target_alias, model)

    def set_reasoning(
        self,
        chat_id: int,
        reasoning_effort: str | None,
        *,
        alias: str | None = None,
    ) -> None:
        target_alias = alias or self._service.get_active_alias(chat_id)
        self._service.set_reasoning(chat_id, target_alias, reasoning_effort)

    def set_sandbox(self, chat_id: int, sandbox_mode: str | None, *, alias: str | None = None) -> None:
        target_alias = alias or self._service.get_active_alias(chat_id)
        self._service.set_sandbox(chat_id, target_alias, sandbox_mode)

    def attach_session(
        self,
        chat_id: int,
        session_ref: str,
        *,
        alias: str | None = None,
    ) -> SessionAttachment:
        target_alias = alias or self._service.get_active_alias(chat_id)
        return self._service.attach_session(
            chat_id=chat_id,
            alias=target_alias,
            session_ref=session_ref,
        )

    def export_vscode(self, chat_id: int, *, alias: str | None = None) -> SessionExport:
        target_alias = alias or self._service.get_active_alias(chat_id)
        return self._service.export_vscode(chat_id=chat_id, alias=target_alias)

    def sync_vscode(self, chat_id: int, *, alias: str | None = None) -> SessionExport:
        target_alias = alias or self._service.get_active_alias(chat_id)
        return self._service.sync_vscode(chat_id=chat_id, alias=target_alias)

    def clone_vscode(self, chat_id: int, *, alias: str | None = None, title: str | None = None) -> SessionClone:
        target_alias = alias or self._service.get_active_alias(chat_id)
        return self._service.clone_vscode(chat_id=chat_id, alias=target_alias, title=title)

    def delete_vscode_copy(self, session_id: str) -> Path:
        return self._service.delete_vscode_copy(session_id)

    def ask(self, chat_id: int, prompt: str, *, alias: str | None = None) -> CodexRunResult:
        if not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        target_alias = alias or self._service.get_active_alias(chat_id)
        self._service.run_startup_checks()
        return self._service.run_prompt(
            chat_id=chat_id,
            alias=target_alias,
            prompt=prompt,
        )
