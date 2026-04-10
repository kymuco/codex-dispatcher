from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..accounts import AccountManager
from ..codex_runner import CodexRunResult, CodexService
from ..config import AppConfig
from ..diagnostics import startup_report
from ..session_manager import SessionAttachment, SessionClone, SessionExport, SessionManager
from ..state import StateStore


class StartupCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptJob:
    chat_id: int
    alias: str
    prompt: str
    reply_to_message_id: int | None


@dataclass(frozen=True)
class AccountEntry:
    name: str
    is_active: bool


@dataclass(frozen=True)
class StatusSnapshot:
    active_alias: str
    session: str
    last_account: str
    model: str
    reasoning: str
    sandbox: str
    default_account: str
    queue_size: int
    worker_busy: bool


@dataclass(frozen=True)
class HealthSnapshot:
    bot_status: str
    codex_binary: str
    workspace: str
    accounts: str
    default_account: str
    queue_size: int
    worker_busy: bool
    active_alias: str
    session: str


@dataclass(frozen=True)
class ThreadSummary:
    alias: str
    is_active: bool
    session: str
    last_account: str


@dataclass(frozen=True)
class ThreadsSnapshot:
    active_alias: str
    items: tuple[ThreadSummary, ...]


@dataclass(frozen=True)
class SettingsSnapshot:
    active_alias: str
    model: str
    reasoning: str
    sandbox: str


@dataclass(frozen=True)
class SessionIdSnapshot:
    active_alias: str
    session_id: str | None


class DispatcherService:
    def __init__(
        self,
        config: AppConfig,
        *,
        queue_size_getter: Callable[[], int] | None = None,
        worker_busy_getter: Callable[[], bool] | None = None,
    ) -> None:
        self.config = config
        data_dir = config.config_path.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        self.state = StateStore(data_dir / "bot_state.json")
        self.accounts = AccountManager(config, self.state)
        self.sessions = SessionManager(config, self.state)
        self.startup_repairs = self.sessions.repair_colliding_local_sessions()
        self.codex: CodexService | None = None

        self._queue_size_getter = queue_size_getter or (lambda: 0)
        self._worker_busy_getter = worker_busy_getter or (lambda: False)

    def startup_report(self) -> dict[str, Any]:
        return startup_report(self.config)

    def run_startup_checks(self) -> None:
        report = self.startup_report()
        issues = report.get("issues")
        if isinstance(issues, list) and issues:
            raise StartupCheckError(f"Startup check failed: {issues[0]}")
        if self.codex is None:
            self.codex = CodexService(self.config, self.state, self.accounts)

    def get_accounts(self) -> tuple[AccountEntry, ...]:
        active = self.accounts.get_active_account_name()
        return tuple(
            AccountEntry(name=name, is_active=name == active)
            for name in self.accounts.list_account_names()
        )

    def switch_account(self, name: str) -> None:
        self.accounts.set_active_account(name)

    def get_active_alias(self, chat_id: int) -> str:
        return self.state.get_active_thread(chat_id)[0]

    def create_or_select_chat(self, chat_id: int, alias: str) -> str:
        self.state.create_or_select_thread(chat_id, alias)
        return alias

    def use_chat(self, chat_id: int, alias: str) -> None:
        self.state.set_active_alias(chat_id, alias)

    def reset_chat(self, chat_id: int, alias: str) -> None:
        self.state.reset_thread(chat_id, alias)

    def set_model(self, chat_id: int, alias: str, model: str | None) -> None:
        self.state.set_thread_model(chat_id, alias, model)

    def set_reasoning(self, chat_id: int, alias: str, reasoning_effort: str | None) -> None:
        self.state.set_thread_reasoning_effort(chat_id, alias, reasoning_effort)

    def set_sandbox(self, chat_id: int, alias: str, sandbox_mode: str | None) -> None:
        self.state.set_thread_sandbox_mode(chat_id, alias, sandbox_mode)

    def attach_session(self, *, chat_id: int, alias: str, session_ref: str) -> SessionAttachment:
        return self.sessions.attach_to_alias(
            chat_id=chat_id,
            alias=alias,
            session_ref=session_ref,
        )

    def export_vscode(self, *, chat_id: int, alias: str) -> SessionExport:
        return self.sessions.export_alias_to_vscode(chat_id=chat_id, alias=alias)

    def sync_vscode(self, *, chat_id: int, alias: str) -> SessionExport:
        return self.sessions.sync_alias_to_vscode(chat_id=chat_id, alias=alias)

    def clone_vscode(self, *, chat_id: int, alias: str, title: str | None = None) -> SessionClone:
        return self.sessions.clone_alias_to_vscode(chat_id=chat_id, alias=alias, title=title)

    def delete_vscode_copy(self, session_id: str) -> Path:
        return self.sessions.delete_vscode_view_copy(session_id)

    def build_prompt_job(self, *, chat_id: int, prompt: str, reply_to_message_id: int | None) -> PromptJob:
        alias = self.get_active_alias(chat_id)
        return PromptJob(
            chat_id=chat_id,
            alias=alias,
            prompt=prompt,
            reply_to_message_id=reply_to_message_id,
        )

    def run_prompt(self, *, chat_id: int, alias: str, prompt: str) -> CodexRunResult:
        if self.codex is None:
            raise RuntimeError("Dispatcher service is not ready. Startup checks were not completed.")
        return self.codex.run_prompt(chat_id=chat_id, alias=alias, prompt=prompt)

    def get_status(self, chat_id: int) -> StatusSnapshot:
        active_alias, thread = self.state.get_active_thread(chat_id)
        default_account = self.accounts.get_active_account_name() or "-"
        return StatusSnapshot(
            active_alias=active_alias,
            session=self._session_summary_text(thread),
            last_account=self._last_account_text(thread),
            model=self._display_setting(thread.get("model")),
            reasoning=self._display_setting(thread.get("reasoning_effort")),
            sandbox=self._display_setting(thread.get("sandbox_mode")),
            default_account=default_account,
            queue_size=self._safe_queue_size(),
            worker_busy=self._safe_worker_busy(),
        )

    def get_health(self, chat_id: int) -> HealthSnapshot:
        report = self.startup_report()
        active_alias, thread = self.state.get_active_thread(chat_id)
        default_account = self.accounts.get_active_account_name() or "-"
        bot_status = "ready" if bool(report.get("ready")) else "not ready"
        return HealthSnapshot(
            bot_status=bot_status,
            codex_binary=str(report.get("codex_binary", "unknown")),
            workspace=str(report.get("workspace", "unknown")),
            accounts=str(report.get("accounts", "unknown")),
            default_account=default_account,
            queue_size=self._safe_queue_size(),
            worker_busy=self._safe_worker_busy(),
            active_alias=active_alias,
            session=self._session_summary_text(thread),
        )

    def list_threads(self, chat_id: int) -> ThreadsSnapshot:
        active_alias, _, threads = self.state.list_threads(chat_id)
        ordered = sorted(threads.items(), key=lambda item: (item[0] != active_alias, item[0].lower()))
        items = tuple(
            ThreadSummary(
                alias=alias,
                is_active=alias == active_alias,
                session=self._session_summary_text(thread),
                last_account=self._last_account_text(thread),
            )
            for alias, thread in ordered
        )
        return ThreadsSnapshot(active_alias=active_alias, items=items)

    def get_settings(self, chat_id: int) -> SettingsSnapshot:
        active_alias, thread = self.state.get_active_thread(chat_id)
        return SettingsSnapshot(
            active_alias=active_alias,
            model=self._display_setting(thread.get("model")),
            reasoning=self._display_setting(thread.get("reasoning_effort")),
            sandbox=self._display_setting(thread.get("sandbox_mode")),
        )

    def get_session_id(self, chat_id: int) -> SessionIdSnapshot:
        active_alias, thread = self.state.get_active_thread(chat_id)
        session_id = thread.get("session_id")
        value = session_id.strip() if isinstance(session_id, str) and session_id.strip() else None
        return SessionIdSnapshot(active_alias=active_alias, session_id=value)

    @staticmethod
    def _session_summary_text(thread: dict[str, Any]) -> str:
        session_id = thread.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            return "started"
        return "not started"

    @staticmethod
    def _last_account_text(thread: dict[str, Any]) -> str:
        last_account = thread.get("last_account")
        if isinstance(last_account, str) and last_account.strip():
            return last_account.strip()
        return "-"

    @staticmethod
    def _display_setting(value: object) -> str:
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized.lower() in {"default", "clear", "none", "off"}:
                return "default"
            return normalized
        return "default"

    def _safe_queue_size(self) -> int:
        try:
            return max(0, int(self._queue_size_getter()))
        except (TypeError, ValueError):
            return 0

    def _safe_worker_busy(self) -> bool:
        try:
            return bool(self._worker_busy_getter())
        except (TypeError, ValueError):
            return False
