from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .accounts import AccountManager
from .codex_runner import CodexRunResult, CodexService
from .config import AppConfig
from .session_manager import SessionManager
from .state import StateStore
from .telegram_api import TelegramApiError, TelegramClient


@dataclass
class CodexJob:
    chat_id: int
    alias: str
    prompt: str
    reply_to_message_id: int | None


class CodexTelegramBot:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        data_dir = config.config_path.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        self.state = StateStore(data_dir / "bot_state.json")
        self.accounts = AccountManager(config, self.state)
        self.sessions = SessionManager(config, self.state)
        self._startup_repairs = self.sessions.repair_colliding_local_sessions()
        self.codex = CodexService(config, self.state, self.accounts)
        self.telegram = TelegramClient(config.telegram_token)

        self._jobs: queue.Queue[CodexJob] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_busy = threading.Event()
        self._last_update_id: int | None = None
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="codex-worker")

    def run_forever(self) -> None:
        if self._startup_repairs:
            print(f"Repaired {len(self._startup_repairs)} colliding local session(s).")
        self._worker.start()
        print("Codex Telegram bot is running. Press Ctrl+C to stop.")
        try:
            while not self._stop_event.is_set():
                try:
                    updates = self.telegram.get_updates(
                        offset=self._next_offset(),
                        timeout_seconds=self.config.polling_timeout_seconds,
                    )
                    for update in updates:
                        self._handle_update(update)
                except TelegramApiError as exc:
                    print(f"Telegram API error: {exc}")
                    time.sleep(self.config.polling_retry_delay_seconds)
                except Exception as exc:  # noqa: BLE001
                    print(f"Unexpected polling error: {exc}")
                    time.sleep(self.config.polling_retry_delay_seconds)
        except KeyboardInterrupt:
            print("Stopping bot...")
        finally:
            self._stop_event.set()
            self._worker.join(timeout=2)

    def _next_offset(self) -> int | None:
        if self._last_update_id is None:
            return None
        return self._last_update_id + 1

    def _handle_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            self._last_update_id = update_id

        message = update.get("message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat")
        if not isinstance(chat, dict):
            return

        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return

        if self.config.allowed_chat_ids and chat_id not in self.config.allowed_chat_ids:
            self.telegram.send_message(chat_id=chat_id, text="This bot is not enabled for this chat.")
            return

        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return

        if text.startswith("/"):
            self._handle_command(chat_id, message.get("message_id"), text.strip())
            return

        self._enqueue_prompt(
            chat_id=chat_id,
            reply_to_message_id=message.get("message_id"),
            prompt=text.strip(),
        )

    def _handle_command(self, chat_id: int, reply_to_message_id: int | None, text: str) -> None:
        command_token, _, args = text.partition(" ")
        command = command_token.split("@", 1)[0].lower()
        args = args.strip()

        try:
            if command in {"/start", "/help"}:
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._help_text(),
                )
            elif command == "/chatid":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=f"Current chat_id: {chat_id}",
                )
            elif command == "/accounts":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._accounts_text(),
                )
            elif command == "/settings":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._settings_text(chat_id),
                )
            elif command == "/switch":
                if not args:
                    raise ValueError("Usage: /switch <account>")
                self.accounts.set_active_account(args)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=f"Default account changed to: {args}",
                )
            elif command == "/status":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._status_text(chat_id),
                )
            elif command == "/threads":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._threads_text(chat_id),
                )
            elif command == "/attachsession":
                if not args:
                    raise ValueError("Usage: /attachsession <session_id_or_path>")
                alias, _ = self.state.get_active_thread(chat_id)
                attachment = self.sessions.attach_to_alias(
                    chat_id=chat_id,
                    alias=alias,
                    session_ref=args,
                )
                source = "imported" if attachment.imported else "linked"
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=(
                        f"Session attached to local chat '{alias}'.\n"
                        f"Source session id: {attachment.source_session_id}\n"
                        f"Local session id: {attachment.session_id}\n"
                        f"Mode: {source}\n"
                        f"Rekeyed: {'yes' if attachment.rekeyed else 'no'}\n"
                        f"Stored at: {attachment.target_file}"
                    ),
                )
            elif command == "/exportvscode":
                alias = args or self.state.get_active_thread(chat_id)[0]
                export = self.sessions.export_alias_to_vscode(chat_id=chat_id, alias=alias)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=(
                        f"Session exported from local chat '{alias}' to VSCode home.\n"
                        f"Session id: {export.session_id}\n"
                        f"Action: {export.action}\n"
                        f"Stored at: {export.target_file}"
                    ),
                )
            elif command == "/syncvscode":
                alias = args or self.state.get_active_thread(chat_id)[0]
                export = self.sessions.sync_alias_to_vscode(chat_id=chat_id, alias=alias)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=(
                        f"Session synced from local chat '{alias}' into VSCode home.\n"
                        f"Session id: {export.session_id}\n"
                        f"Action: {export.action}\n"
                        f"Stored at: {export.target_file}"
                    ),
                )
            elif command == "/clonevscode":
                alias = self.state.get_active_thread(chat_id)[0]
                clone = self.sessions.clone_alias_to_vscode(chat_id=chat_id, alias=alias, title=args or None)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=(
                        f"VSCode view copy created from local chat '{alias}'.\n"
                        f"Source session id: {clone.source_session_id}\n"
                        f"Cloned session id: {clone.cloned_session_id}\n"
                        f"Thread name: {clone.thread_name}\n"
                        f"Rollout path: {clone.target_file}\n"
                        "For reliability, refresh or reopen VSCode before switching threads."
                    ),
                )
            elif command == "/deletevscodecopy":
                if not args:
                    raise ValueError("Usage: /deletevscodecopy <cloned_session_id>")
                deleted_file = self.sessions.delete_vscode_view_copy(args)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=(
                        f"VSCode view copy deleted. Rollout path was: {deleted_file}\n"
                        "For reliability, refresh or reopen VSCode before returning to the original thread."
                    ),
                )
            elif command == "/newchat":
                alias = args or datetime.now(tz=UTC).strftime("chat-%Y%m%d-%H%M%S")
                self.state.create_or_select_thread(chat_id, alias)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=f"Active local chat: {alias}",
                )
            elif command == "/use":
                if not args:
                    raise ValueError("Usage: /use <alias>")
                self.state.set_active_alias(chat_id, args)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=f"Switched to local chat: {args}",
                )
            elif command == "/resetchat":
                alias, _ = self.state.get_active_thread(chat_id)
                self.state.reset_thread(chat_id, alias)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=f"Session for local chat '{alias}' was reset. The next prompt will start a new thread.",
                )
            elif command == "/edit":
                if not args:
                    raise ValueError("Usage: /edit on|off|full|default")
                sandbox_mode = self._parse_edit_mode(args)
                alias, _ = self.state.get_active_thread(chat_id)
                self.state.set_thread_sandbox_mode(chat_id, alias, sandbox_mode)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._sandbox_confirmation_text(alias, sandbox_mode, shorthand=True),
                )
            elif command == "/fullaccess":
                alias, _ = self.state.get_active_thread(chat_id)
                self.state.set_thread_sandbox_mode(chat_id, alias, "danger-full-access")
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._sandbox_confirmation_text(alias, "danger-full-access", shorthand=True),
                )
            elif command == "/sandbox":
                if not args:
                    raise ValueError("Usage: /sandbox <read-only|workspace-write|danger-full-access|default>")
                sandbox_mode = self._parse_sandbox_mode(args)
                alias, _ = self.state.get_active_thread(chat_id)
                self.state.set_thread_sandbox_mode(chat_id, alias, sandbox_mode)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._sandbox_confirmation_text(alias, sandbox_mode),
                )
            elif command == "/model":
                if not args:
                    raise ValueError("Usage: /model <name|default>")
                model = self._parse_optional_value(args)
                alias, _ = self.state.get_active_thread(chat_id)
                self.state.set_thread_model(chat_id, alias, model)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._setting_confirmation_text(alias, "Model", model),
                )
            elif command == "/reasoning":
                if not args:
                    raise ValueError("Usage: /reasoning <low|medium|high|xhigh|default>")
                reasoning_effort = self._parse_reasoning_effort(args)
                alias, _ = self.state.get_active_thread(chat_id)
                self.state.set_thread_reasoning_effort(chat_id, alias, reasoning_effort)
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._setting_confirmation_text(alias, "Reasoning", reasoning_effort),
                )
            elif command == "/ask":
                if not args:
                    raise ValueError("Usage: /ask <text>")
                self._enqueue_prompt(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    prompt=args,
                )
            else:
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text="Unknown command. Use /help.",
                )
        except KeyError as exc:
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                text=f"Unknown local chat or account: {exc}",
            )
        except ValueError as exc:
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                text=str(exc),
            )
        except FileNotFoundError as exc:
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                text=str(exc),
            )

    def _enqueue_prompt(self, *, chat_id: int, reply_to_message_id: int | None, prompt: str) -> None:
        alias, _ = self.state.get_active_thread(chat_id)
        job = CodexJob(
            chat_id=chat_id,
            alias=alias,
            prompt=prompt,
            reply_to_message_id=reply_to_message_id,
        )
        self._jobs.put(job)
        queue_size = self._jobs.qsize()
        suffix = "Starting now." if queue_size == 1 and not self._worker_busy.is_set() else f"Queue size: {queue_size}."
        self.telegram.send_message(
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            text=f"Prompt queued for local chat '{alias}'. {suffix}",
        )

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._jobs.get(timeout=0.5)
            except queue.Empty:
                continue

            self._worker_busy.set()
            try:
                result = self.codex.run_prompt(chat_id=job.chat_id, alias=job.alias, prompt=job.prompt)
                self._send_result(job, result)
            except Exception as exc:  # noqa: BLE001
                self.telegram.send_message(
                    chat_id=job.chat_id,
                    reply_to_message_id=job.reply_to_message_id,
                    text=f"Codex run failed: {exc}",
                )
            finally:
                self._worker_busy.clear()
                self._jobs.task_done()

    def _send_result(self, job: CodexJob, result: CodexRunResult) -> None:
        if result.success:
            self.telegram.send_message(
                chat_id=job.chat_id,
                reply_to_message_id=job.reply_to_message_id,
                text=result.final_message,
            )
            return

        error_text = (
            f"Codex did not finish successfully.\n"
            f"Account: {result.account_name}\n"
            f"Return code: {result.returncode}\n\n"
            f"{result.final_message}"
        )
        self.telegram.send_message(
            chat_id=job.chat_id,
            reply_to_message_id=job.reply_to_message_id,
            text=error_text,
        )

    def _accounts_text(self) -> str:
        active = self.accounts.get_active_account_name()
        lines = ["Codex accounts:"]
        for name in self.accounts.list_account_names():
            marker = "active" if name == active else "idle"
            lines.append(f"- {name} [{marker}]")
        return "\n".join(lines)

    def _status_text(self, chat_id: int) -> str:
        active_alias, thread = self.state.get_active_thread(chat_id)
        active_account = self.accounts.get_active_account_name()
        queue_size = self._jobs.qsize()
        busy = "yes" if self._worker_busy.is_set() else "no"
        session_id = thread.get("session_id") or "not started"
        last_account = thread.get("last_account") or "unknown"
        return (
            f"Active local chat: {active_alias}\n"
            f"Session id: {session_id}\n"
            f"Last account for this chat: {last_account}\n"
            f"Model: {self._display_setting(thread.get('model'))}\n"
            f"Reasoning: {self._display_setting(thread.get('reasoning_effort'))}\n"
            f"Sandbox: {self._display_setting(thread.get('sandbox_mode'))}\n"
            f"Default account: {active_account}\n"
            f"Queue size: {queue_size}\n"
            f"Worker busy: {busy}"
        )

    def _threads_text(self, chat_id: int) -> str:
        active_alias, _, threads = self.state.list_threads(chat_id)
        lines = ["Local chats:"]
        for alias, thread in sorted(threads.items()):
            marker = "active" if alias == active_alias else "idle"
            session_id = thread.get("session_id") or "new"
            last_account = thread.get("last_account") or "-"
            lines.append(f"- {alias} [{marker}] session={session_id} account={last_account}")
        return "\n".join(lines)

    def _settings_text(self, chat_id: int) -> str:
        active_alias, thread = self.state.get_active_thread(chat_id)
        return (
            f"Codex settings for local chat '{active_alias}':\n"
            f"- Model: {self._display_setting(thread.get('model'))}\n"
            f"- Reasoning: {self._display_setting(thread.get('reasoning_effort'))}\n"
            f"- Sandbox: {self._display_setting(thread.get('sandbox_mode'))}\n"
            "These settings apply to the next Codex prompt for this chat."
        )

    @staticmethod
    def _display_setting(value: object) -> str:
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized.lower() in {"default", "clear", "none", "off"}:
                return "default"
            return normalized
        return "default"

    @staticmethod
    def _parse_optional_value(raw_value: str) -> str | None:
        value = raw_value.strip()
        if not value:
            raise ValueError("Value must not be empty.")
        if value.lower() in {"default", "clear", "off", "none"}:
            return None
        return value

    @staticmethod
    def _parse_reasoning_effort(raw_value: str) -> str | None:
        value = raw_value.strip().lower()
        if value in {"default", "clear", "off", "none"}:
            return None
        if value not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("Usage: /reasoning <low|medium|high|xhigh|default>")
        return value

    @staticmethod
    def _parse_sandbox_mode(raw_value: str) -> str | None:
        value = raw_value.strip().lower()
        if value in {"default", "clear", "none"}:
            return None
        if value in {"read-only", "read", "readonly", "off"}:
            return "read-only"
        if value in {"workspace-write", "write", "on", "edit"}:
            return "workspace-write"
        if value in {"danger-full-access", "full", "danger", "unsafe"}:
            return "danger-full-access"
        raise ValueError("Usage: /sandbox <read-only|workspace-write|danger-full-access|default>")

    @staticmethod
    def _parse_edit_mode(raw_value: str) -> str | None:
        value = raw_value.strip().lower()
        if value in {"default", "clear", "none"}:
            return None
        if value in {"off", "read", "readonly", "read-only"}:
            return "read-only"
        if value in {"on", "write", "workspace-write"}:
            return "workspace-write"
        if value in {"full", "danger", "danger-full-access"}:
            return "danger-full-access"
        raise ValueError("Usage: /edit on|off|full|default")

    @staticmethod
    def _setting_confirmation_text(alias: str, label: str, value: str | None) -> str:
        return f"{label} for local chat '{alias}' set to: {value or 'default'}"

    @staticmethod
    def _sandbox_confirmation_text(alias: str, sandbox_mode: str | None, *, shorthand: bool = False) -> str:
        mode = sandbox_mode or "default"
        if mode == "danger-full-access":
            warning = " Warning: this removes sandboxing."
        else:
            warning = ""
        if shorthand and mode == "workspace-write":
            prefix = "File editing enabled"
        elif shorthand and mode == "read-only":
            prefix = "File editing disabled"
        elif shorthand and mode == "danger-full-access":
            prefix = "Full access enabled"
        else:
            prefix = f"Sandbox for local chat '{alias}' set to: {mode}"
        return f"{prefix}.{warning}".strip()

    @staticmethod
    def _help_text() -> str:
        return (
            "Commands:\n"
            "/chatid - show the current Telegram chat id\n"
            "/accounts - list accounts\n"
            "/settings - show Codex model, reasoning, and sandbox overrides for the active local chat\n"
            "/switch <account> - change default account for future runs\n"
            "/status - show status for the current local chat\n"
            "/threads - list local chats\n"
            "/attachsession <session_id_or_path> - bind an existing Codex session to the current local chat\n"
            "/exportvscode [alias] - safely expose the local chat in VSCode without overwriting existing sessions\n"
            "/syncvscode [alias] - explicitly update an existing VSCode session with the current local chat\n"
            "/clonevscode [title] - create a temporary full-history VSCode thread copy for viewing\n"
            "/deletevscodecopy <cloned_session_id> - delete only a temporary VSCode view copy created by /clonevscode\n"
            "/newchat [alias] - create a new local chat\n"
            "/use <alias> - switch to an existing local chat\n"
            "/resetchat - clear the current session id\n"
            "/edit on|off|full|default - quick toggle for file editing access\n"
            "/fullaccess - enable danger-full-access for the active local chat\n"
            "/sandbox <read-only|workspace-write|danger-full-access|default> - set sandbox mode explicitly\n"
            "/model <name|default> - choose the Codex model for the active local chat\n"
            "/reasoning <low|medium|high|xhigh|default> - set the reasoning effort for the active local chat\n"
            "/ask <text> - send a prompt to Codex\n\n"
            "Plain text without a command is also sent to Codex."
        )
