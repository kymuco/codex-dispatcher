from __future__ import annotations

import queue
import threading
import time
import uuid
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
        self._confirmations: dict[str, dict[str, Any]] = {}

    def run_forever(self) -> None:
        if self._startup_repairs:
            print(f"Repaired {len(self._startup_repairs)} colliding local session(s).")
        self._sync_telegram_command_hints()
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

    def _sync_telegram_command_hints(self) -> None:
        try:
            self.telegram.set_my_commands(commands=self._telegram_command_hints())
        except TelegramApiError as exc:
            print(f"Failed to sync Telegram command hints: {exc}")

    def _handle_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            self._last_update_id = update_id

        callback_query = update.get("callback_query")
        if isinstance(callback_query, dict):
            self._handle_callback_query(callback_query)
            return

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

        text = text.strip()
        quick_action_command = self._quick_action_command(text)
        if quick_action_command == "__ask_hint__":
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=message.get("message_id"),
                text="Send any plain text message and I will run it as a Codex prompt.",
                reply_markup=self._main_reply_keyboard(),
            )
            return
        if isinstance(quick_action_command, str):
            text = quick_action_command

        if text.startswith("/"):
            self._handle_command(chat_id, message.get("message_id"), text)
            return

        self._enqueue_prompt(
            chat_id=chat_id,
            reply_to_message_id=message.get("message_id"),
            prompt=text,
        )

    def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        callback_query_id = callback_query.get("id")
        data = callback_query.get("data")
        message = callback_query.get("message")
        if not isinstance(callback_query_id, str):
            return
        if not isinstance(data, str):
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Unsupported action.",
                show_alert=False,
            )
            return

        chat_id: int | None = None
        message_id: int | None = None
        if isinstance(message, dict):
            message_id_raw = message.get("message_id")
            if isinstance(message_id_raw, int):
                message_id = message_id_raw
            chat = message.get("chat")
            if isinstance(chat, dict):
                chat_id_raw = chat.get("id")
                if isinstance(chat_id_raw, int):
                    chat_id = chat_id_raw

        if chat_id is None:
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Unsupported action context.",
                show_alert=False,
            )
            return

        if self.config.allowed_chat_ids and chat_id not in self.config.allowed_chat_ids:
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="This bot is not enabled for this chat.",
                show_alert=True,
            )
            return

        prefix, _, remainder = data.partition(":")
        token, _, decision = remainder.partition(":")
        if prefix != "cfm" or not token or decision not in {"yes", "no"}:
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Unknown action.",
                show_alert=False,
            )
            return

        confirmation = self._confirmations.pop(token, None)
        if confirmation is None:
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="This confirmation has expired.",
                show_alert=False,
            )
            return

        if int(confirmation.get("chat_id", -1)) != chat_id:
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="This action belongs to another chat.",
                show_alert=True,
            )
            return

        if message_id is not None:
            try:
                self.telegram.clear_inline_keyboard(chat_id=chat_id, message_id=message_id)
            except TelegramApiError:
                pass

        if decision == "no":
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Cancelled.",
                show_alert=False,
            )
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                text="Action cancelled.",
            )
            return

        try:
            self._apply_confirmation(chat_id=chat_id, reply_to_message_id=message_id, confirmation=confirmation)
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Done.",
                show_alert=False,
            )
        except (KeyError, ValueError, FileNotFoundError) as exc:
            self.telegram.answer_callback_query(
                callback_query_id=callback_query_id,
                text="Failed.",
                show_alert=True,
            )
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                text=str(exc),
            )

    def _handle_command(self, chat_id: int, reply_to_message_id: int | None, text: str) -> None:
        command_token, _, args = text.partition(" ")
        command = self._resolve_command(command_token.split("@", 1)[0].lower())
        args = args.strip()

        try:
            if command == "/start":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._start_text(),
                    reply_markup=self._main_reply_keyboard(),
                )
            elif command == "/help":
                help_text = self._command_help_text(args) if args else self._help_text()
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=help_text,
                    reply_markup=self._main_reply_keyboard(),
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
                    raise ValueError(self._usage_error("/switch"))
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
            elif command == "/sessionid":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._session_id_text(chat_id),
                )
            elif command == "/threads":
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._threads_text(chat_id),
                )
            elif command == "/attachsession":
                if not args:
                    raise ValueError(self._usage_error("/attachsession"))
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
                        f"Session attached to local chat '{alias}'.\n\n"
                        f"Source session id: {attachment.source_session_id}\n"
                        f"Local session id: {attachment.session_id}\n"
                        f"Mode: {source}\n"
                        f"Rekeyed: {'yes' if attachment.rekeyed else 'no'}\n"
                        f"Stored at: {attachment.target_file}\n\n"
                        "Quick command:\n"
                        f"/attachsession {attachment.session_id}"
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
                        f"VSCode view copy created from local chat '{alias}'.\n\n"
                        f"Source session id: {clone.source_session_id}\n"
                        f"Cloned session id: {clone.cloned_session_id}\n"
                        f"Thread name: {clone.thread_name}\n"
                        f"Rollout path: {clone.target_file}\n"
                        "\n"
                        "Quick commands:\n"
                        f"/attachsession {clone.cloned_session_id}\n"
                        f"/deletevscodecopy {clone.cloned_session_id}\n"
                        "\n"
                        "For reliability, refresh or reopen VSCode before switching threads."
                    ),
                )
            elif command == "/deletevscodecopy":
                if not args:
                    raise ValueError(self._usage_error("/deletevscodecopy"))
                self._request_confirmation(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    action="delete_vscode_copy",
                    payload={"session_id": args},
                    prompt=(
                        "Delete temporary VSCode view copy?\n"
                        f"Cloned session id: {args}"
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
                    raise ValueError(self._usage_error("/use"))
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
                    raise ValueError(self._usage_error("/edit"))
                sandbox_mode = self._parse_edit_mode(args)
                alias, _ = self.state.get_active_thread(chat_id)
                if sandbox_mode == "danger-full-access":
                    self._request_confirmation(
                        chat_id=chat_id,
                        reply_to_message_id=reply_to_message_id,
                        action="set_fullaccess",
                        payload={"alias": alias},
                        prompt=(
                            f"Enable full access for local chat '{alias}'?\n"
                            "This disables sandboxing and approvals."
                        ),
                    )
                else:
                    self.state.set_thread_sandbox_mode(chat_id, alias, sandbox_mode)
                    self.telegram.send_message(
                        chat_id=chat_id,
                        reply_to_message_id=reply_to_message_id,
                        text=self._sandbox_confirmation_text(alias, sandbox_mode, shorthand=True),
                    )
            elif command == "/fullaccess":
                alias, _ = self.state.get_active_thread(chat_id)
                self._request_confirmation(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    action="set_fullaccess",
                    payload={"alias": alias},
                    prompt=(
                        f"Enable full access for local chat '{alias}'?\n"
                        "This disables sandboxing and approvals."
                    ),
                )
            elif command == "/sandbox":
                if not args:
                    raise ValueError(self._usage_error("/sandbox"))
                sandbox_mode = self._parse_sandbox_mode(args)
                alias, _ = self.state.get_active_thread(chat_id)
                if sandbox_mode == "danger-full-access":
                    self._request_confirmation(
                        chat_id=chat_id,
                        reply_to_message_id=reply_to_message_id,
                        action="set_fullaccess",
                        payload={"alias": alias},
                        prompt=(
                            f"Enable full access for local chat '{alias}'?\n"
                            "This disables sandboxing and approvals."
                        ),
                    )
                else:
                    self.state.set_thread_sandbox_mode(chat_id, alias, sandbox_mode)
                    self.telegram.send_message(
                        chat_id=chat_id,
                        reply_to_message_id=reply_to_message_id,
                        text=self._sandbox_confirmation_text(alias, sandbox_mode),
                    )
            elif command == "/model":
                if not args:
                    raise ValueError(self._usage_error("/model"))
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
                    raise ValueError(self._usage_error("/reasoning"))
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
                    raise ValueError(self._usage_error("/ask"))
                self._enqueue_prompt(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    prompt=args,
                )
            else:
                self.telegram.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    text=self._unknown_command_text(),
                )
        except KeyError as exc:
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                text=self._unknown_reference_text(command, exc),
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
                text=self._file_not_found_text(command, exc),
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
        session_id = self._session_id_value(thread)
        last_account = thread.get("last_account") or "unknown"
        quick_commands = [f"/use {active_alias}"]
        attach_command = self._attach_command_for_session(thread.get("session_id"))
        if attach_command is not None:
            quick_commands.append(attach_command)
        quick_commands.append("/clonevscode")
        quick_commands.append("/threads")
        return (
            "Status\n\n"
            f"Local chat: {active_alias}\n"
            f"Session id: {session_id}\n"
            f"Last account: {last_account}\n\n"
            "Codex settings\n"
            f"Model: {self._display_setting(thread.get('model'))}\n"
            f"Reasoning: {self._display_setting(thread.get('reasoning_effort'))}\n"
            f"Sandbox: {self._display_setting(thread.get('sandbox_mode'))}\n\n"
            "Runtime\n"
            f"Default account: {active_account}\n"
            f"Queue size: {queue_size}\n"
            f"Worker busy: {busy}\n\n"
            "Quick commands\n"
            f"{'\n'.join(quick_commands)}"
        )

    def _threads_text(self, chat_id: int) -> str:
        active_alias, _, threads = self.state.list_threads(chat_id)
        lines = [f"Local chats ({len(threads)}):", ""]
        ordered_threads = sorted(
            threads.items(),
            key=lambda item: (item[0] != active_alias, item[0].lower()),
        )
        for alias, thread in ordered_threads:
            marker = "active" if alias == active_alias else "idle"
            session_id = self._session_id_value(thread)
            last_account = thread.get("last_account") or "-"
            lines.append(f"[{marker}] {alias}")
            lines.append(f"Session id: {session_id}")
            lines.append(f"Last account: {last_account}")
            lines.append("Quick commands:")
            lines.append(f"/use {alias}")
            attach_command = self._attach_command_for_session(thread.get("session_id"))
            if attach_command is not None:
                lines.append(attach_command)
            lines.append("")
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

    def _session_id_text(self, chat_id: int) -> str:
        active_alias, thread = self.state.get_active_thread(chat_id)
        session_id = thread.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            return (
                f"Local chat: {active_alias}\n"
                "Session id: not started yet.\n"
                "Run /ask <text> first, then use /sessionid again."
            )
        session_id = session_id.strip()
        return (
            f"Local chat: {active_alias}\n"
            f"Session id: {session_id}\n\n"
            "Quick command:\n"
            f"/attachsession {session_id}"
        )

    @staticmethod
    def _session_id_value(thread: dict[str, Any]) -> str:
        session_id = thread.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
        return "not started"

    @staticmethod
    def _attach_command_for_session(session_id: object) -> str | None:
        if isinstance(session_id, str) and session_id.strip():
            return f"/attachsession {session_id.strip()}"
        return None

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

    @classmethod
    def _parse_reasoning_effort(cls, raw_value: str) -> str | None:
        raw = raw_value.strip()
        value = raw.lower()
        if value in {"default", "clear", "off", "none"}:
            return None
        if value not in {"low", "medium", "high", "xhigh"}:
            raise ValueError(
                cls._invalid_argument_text(
                    command="/reasoning",
                    problem=f"Invalid reasoning level: {raw}.",
                )
            )
        return value

    @classmethod
    def _parse_sandbox_mode(cls, raw_value: str) -> str | None:
        raw = raw_value.strip()
        value = raw.lower()
        if value in {"default", "clear", "none"}:
            return None
        if value in {"read-only", "read", "readonly", "off"}:
            return "read-only"
        if value in {"workspace-write", "write", "on", "edit"}:
            return "workspace-write"
        if value in {"danger-full-access", "full", "danger", "unsafe"}:
            return "danger-full-access"
        raise ValueError(
            cls._invalid_argument_text(
                command="/sandbox",
                problem=f"Invalid sandbox mode: {raw}.",
            )
        )

    @classmethod
    def _parse_edit_mode(cls, raw_value: str) -> str | None:
        raw = raw_value.strip()
        value = raw.lower()
        if value in {"default", "clear", "none"}:
            return None
        if value in {"off", "read", "readonly", "read-only"}:
            return "read-only"
        if value in {"on", "write", "workspace-write"}:
            return "workspace-write"
        if value in {"full", "danger", "danger-full-access"}:
            return "danger-full-access"
        raise ValueError(
            cls._invalid_argument_text(
                command="/edit",
                problem=f"Invalid edit mode: {raw}.",
            )
        )

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

    def _request_confirmation(
        self,
        *,
        chat_id: int,
        reply_to_message_id: int | None,
        action: str,
        payload: dict[str, Any],
        prompt: str,
    ) -> None:
        token = self._register_confirmation(chat_id=chat_id, action=action, payload=payload)
        self.telegram.send_message(
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            text=f"{prompt}\n\nConfirm or cancel:",
            reply_markup=self._confirmation_markup(token),
        )

    def _register_confirmation(
        self,
        *,
        chat_id: int,
        action: str,
        payload: dict[str, Any],
    ) -> str:
        self._prune_confirmations()
        token = uuid.uuid4().hex[:12]
        self._confirmations[token] = {
            "chat_id": chat_id,
            "action": action,
            "payload": payload,
            "created_at": time.time(),
        }
        return token

    def _prune_confirmations(self) -> None:
        expiration_seconds = 3600
        now = time.time()
        stale_tokens = [
            token
            for token, confirmation in self._confirmations.items()
            if now - float(confirmation.get("created_at", 0)) > expiration_seconds
        ]
        for token in stale_tokens:
            self._confirmations.pop(token, None)

    @staticmethod
    def _confirmation_markup(token: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Confirm", "callback_data": f"cfm:{token}:yes"},
                    {"text": "Cancel", "callback_data": f"cfm:{token}:no"},
                ]
            ]
        }

    def _apply_confirmation(
        self,
        *,
        chat_id: int,
        reply_to_message_id: int | None,
        confirmation: dict[str, Any],
    ) -> None:
        action = confirmation.get("action")
        payload = confirmation.get("payload")
        if not isinstance(action, str) or not isinstance(payload, dict):
            raise ValueError("Invalid confirmation payload.")

        if action == "set_fullaccess":
            alias = payload.get("alias")
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("Missing alias for full access confirmation.")
            self.state.set_thread_sandbox_mode(chat_id, alias, "danger-full-access")
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                text=self._sandbox_confirmation_text(alias, "danger-full-access", shorthand=True),
            )
            return

        if action == "delete_vscode_copy":
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                raise ValueError("Missing cloned session id for delete action.")
            deleted_file = self.sessions.delete_vscode_view_copy(session_id)
            self.telegram.send_message(
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                text=(
                    f"VSCode view copy deleted. Rollout path was: {deleted_file}\n"
                    "For reliability, refresh or reopen VSCode before returning to the original thread."
                ),
            )
            return

        raise ValueError(f"Unknown confirmation action: {action}")

    @classmethod
    def _main_reply_keyboard(cls) -> dict[str, Any]:
        return {
            "keyboard": [
                [{"text": "Ask"}, {"text": "Status"}, {"text": "Chats"}],
                [{"text": "Settings"}, {"text": "Session ID"}, {"text": "Help"}],
                [{"text": "New chat"}, {"text": "Full access"}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
            "input_field_placeholder": "Type a prompt or choose an action",
        }

    @classmethod
    def _quick_action_command(cls, text: str) -> str | None:
        normalized = text.strip().lower()
        mapping = {
            "ask": "__ask_hint__",
            "status": "/status",
            "chats": "/chats",
            "settings": "/settings",
            "session id": "/sessionid",
            "new chat": "/newchat",
            "help": "/help",
            "full access": "/fullaccess",
        }
        return mapping.get(normalized)

    @classmethod
    def _command_docs(cls) -> tuple[dict[str, Any], ...]:
        return (
            {
                "command": "/help",
                "menu": "help",
                "summary": "show command list or mini docs",
                "usage": "/help [command]",
                "aliases": ("/doc",),
                "details": "Open mini documentation for a specific command.",
                "examples": ("/help", "/help chats", "/doc attach"),
            },
            {
                "command": "/status",
                "menu": "status",
                "summary": "show active chat and runtime state",
                "usage": "/status",
                "aliases": ("/state",),
                "details": "Shows active local chat, session id, account, model, reasoning, sandbox, and queue.",
                "examples": ("/status",),
            },
            {
                "command": "/threads",
                "menu": "chats",
                "summary": "list local chats in this Telegram chat",
                "usage": "/threads",
                "aliases": ("/chats",),
                "details": "Displays all local chats with quick commands to switch or attach.",
                "examples": ("/threads", "/chats"),
            },
            {
                "command": "/sessionid",
                "menu": "sessionid",
                "summary": "show active session id and attach command",
                "usage": "/sessionid",
                "aliases": ("/sid",),
                "details": "Returns the current session id for the active local chat.",
                "examples": ("/sessionid", "/sid"),
            },
            {
                "command": "/newchat",
                "menu": "new",
                "summary": "create and activate a local chat",
                "usage": "/newchat [alias]",
                "aliases": ("/new",),
                "details": "Without alias, creates a timestamped local chat.",
                "examples": ("/newchat", "/new release-notes"),
            },
            {
                "command": "/use",
                "menu": "use",
                "summary": "switch to an existing local chat",
                "usage": "/use <alias>",
                "aliases": ("/chat",),
                "missing_arg": "Missing local chat alias.",
                "details": "Changes active local chat in the current Telegram chat.",
                "examples": ("/use main", "/chat bugfix"),
            },
            {
                "command": "/resetchat",
                "menu": "reset",
                "summary": "clear active session id",
                "usage": "/resetchat",
                "aliases": ("/reset",),
                "details": "Keeps chat alias but resets session id; next prompt starts a new Codex session.",
                "examples": ("/resetchat", "/reset"),
            },
            {
                "command": "/ask",
                "menu": "ask",
                "summary": "send prompt to Codex",
                "usage": "/ask <text>",
                "aliases": ("/q",),
                "missing_arg": "Missing prompt text.",
                "details": "Plain text messages without slash behave the same as /ask.",
                "examples": ("/ask explain this module", "/q run tests"),
            },
            {
                "command": "/accounts",
                "menu": "accounts",
                "summary": "list configured Codex accounts",
                "usage": "/accounts",
                "aliases": ("/accs",),
                "details": "Shows account names and which one is active by default.",
                "examples": ("/accounts", "/accs"),
            },
            {
                "command": "/switch",
                "menu": "account",
                "summary": "change default Codex account",
                "usage": "/switch <account>",
                "aliases": ("/account",),
                "missing_arg": "Missing account name.",
                "details": "Sets the default account for future runs in this bot state.",
                "examples": ("/switch acc2", "/account acc1"),
            },
            {
                "command": "/settings",
                "menu": "settings",
                "summary": "show model/reasoning/sandbox overrides",
                "usage": "/settings",
                "aliases": ("/prefs",),
                "details": "Prints Codex setting overrides for the active local chat.",
                "examples": ("/settings", "/prefs"),
            },
            {
                "command": "/model",
                "menu": "model",
                "summary": "set Codex model for active chat",
                "usage": "/model <name|default>",
                "aliases": (),
                "missing_arg": "Missing model name.",
                "details": "Use 'default' to clear chat-specific model override.",
                "examples": ("/model gpt-5.4", "/model default"),
            },
            {
                "command": "/reasoning",
                "menu": "reasoning",
                "summary": "set reasoning effort",
                "usage": "/reasoning <low|medium|high|xhigh|default>",
                "aliases": (),
                "missing_arg": "Missing reasoning level.",
                "details": "Sets reasoning level for future prompts in this local chat.",
                "examples": ("/reasoning high", "/reasoning default"),
            },
            {
                "command": "/sandbox",
                "menu": "mode",
                "summary": "set sandbox mode",
                "usage": "/sandbox <read-only|workspace-write|danger-full-access|default>",
                "aliases": ("/mode",),
                "missing_arg": "Missing sandbox mode.",
                "details": "Use danger-full-access only when you trust the task and environment.",
                "examples": ("/sandbox workspace-write", "/mode read-only"),
            },
            {
                "command": "/edit",
                "menu": "edit",
                "summary": "quick file-edit toggle",
                "usage": "/edit on|off|full|default",
                "aliases": (),
                "missing_arg": "Missing edit mode.",
                "details": "Shortcut for common sandbox modes: on=workspace-write, off=read-only, full=danger-full-access.",
                "examples": ("/edit on", "/edit full"),
            },
            {
                "command": "/fullaccess",
                "menu": "full",
                "summary": "enable danger-full-access",
                "usage": "/fullaccess",
                "aliases": ("/full",),
                "details": "Requests confirmation because this disables sandbox protections.",
                "examples": ("/fullaccess", "/full"),
            },
            {
                "command": "/attachsession",
                "menu": "attach",
                "summary": "bind session id or rollout file to active chat",
                "usage": "/attachsession <session_id_or_path>",
                "aliases": ("/attach",),
                "missing_arg": "Missing session reference.",
                "details": "Lets you resume an existing Codex session from home index or rollout file path.",
                "examples": ("/attachsession 019d....", "/attach C:\\path\\to\\rollout.jsonl"),
            },
            {
                "command": "/clonevscode",
                "menu": "clone",
                "summary": "create a temporary VSCode view copy",
                "usage": "/clonevscode [title]",
                "aliases": ("/clone",),
                "details": "Creates a separate copy for safe viewing in VSCode without touching original local chat data.",
                "examples": ("/clonevscode", "/clone temp-inspect"),
            },
            {
                "command": "/deletevscodecopy",
                "menu": "deletecopy",
                "summary": "delete temporary VSCode view copy",
                "usage": "/deletevscodecopy <cloned_session_id>",
                "aliases": ("/deletecopy",),
                "missing_arg": "Missing cloned session id.",
                "details": "Deletes only cloned temporary copy created by clone commands.",
                "examples": ("/deletevscodecopy 019d....", "/deletecopy 019d...."),
            },
            {
                "command": "/exportvscode",
                "menu": "exportvscode",
                "summary": "copy local chat to VSCode home safely",
                "usage": "/exportvscode [alias]",
                "aliases": (),
                "details": "Will not overwrite an existing VSCode session with the same id.",
                "examples": ("/exportvscode", "/exportvscode main"),
            },
            {
                "command": "/syncvscode",
                "menu": "syncvscode",
                "summary": "force update VSCode copy from local chat",
                "usage": "/syncvscode [alias]",
                "aliases": (),
                "details": "Explicitly overwrites existing VSCode copy for that session id.",
                "examples": ("/syncvscode", "/syncvscode release"),
            },
            {
                "command": "/chatid",
                "menu": "chatid",
                "summary": "show current Telegram chat id",
                "usage": "/chatid",
                "aliases": ("/id",),
                "details": "Useful when setting allowed_chat_ids in config.",
                "examples": ("/chatid", "/id"),
            },
        )

    @classmethod
    def _command_doc_map(cls) -> dict[str, dict[str, Any]]:
        return {str(doc["command"]): doc for doc in cls._command_docs()}

    @classmethod
    def _command_aliases(cls) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for doc in cls._command_docs():
            command = str(doc["command"]).lower()
            aliases[command] = command
            for alias in doc.get("aliases", ()):
                aliases[str(alias).lower()] = command
        return aliases

    @classmethod
    def _resolve_command(cls, command: str) -> str:
        normalized = command.strip().lower()
        return cls._command_aliases().get(normalized, normalized)

    @classmethod
    def _usage_error(cls, command: str) -> str:
        canonical = cls._resolve_command(command)
        doc = cls._command_doc_map().get(canonical, {})
        problem = str(doc.get("missing_arg", "Missing required argument."))
        return cls._missing_argument_text(
            command=canonical,
            problem=problem,
            example=cls._command_example(canonical),
        )

    @classmethod
    def _command_usage(cls, command: str) -> str:
        canonical = cls._resolve_command(command)
        doc = cls._command_doc_map().get(canonical)
        if not isinstance(doc, dict):
            return canonical
        return str(doc.get("usage", canonical))

    @classmethod
    def _command_example(cls, command: str) -> str | None:
        canonical = cls._resolve_command(command)
        doc = cls._command_doc_map().get(canonical)
        if not isinstance(doc, dict):
            return None
        examples = doc.get("examples")
        if not isinstance(examples, tuple) or not examples:
            return None
        first = examples[0]
        return str(first) if isinstance(first, str) and first.strip() else None

    @classmethod
    def _help_ref(cls, command: str) -> str:
        canonical = cls._resolve_command(command).strip()
        if canonical.startswith("/"):
            return canonical[1:]
        return canonical or "help"

    @classmethod
    def _missing_argument_text(cls, *, command: str, problem: str, example: str | None = None) -> str:
        lines = [
            problem,
            f"Use: {cls._command_usage(command)}",
        ]
        if example:
            lines.append(f"Example: {example}")
        lines.append(f"Help: /help {cls._help_ref(command)}")
        return "\n".join(lines)

    @classmethod
    def _invalid_argument_text(cls, *, command: str, problem: str, example: str | None = None) -> str:
        return cls._missing_argument_text(
            command=command,
            problem=problem,
            example=example or cls._command_example(command),
        )

    @staticmethod
    def _unknown_command_text() -> str:
        return "Unknown command.\nUse /help for the command list."

    @classmethod
    def _unknown_reference_text(cls, command: str, exc: KeyError) -> str:
        canonical = cls._resolve_command(command)
        missing = str(exc).strip().strip("'\"")
        if canonical == "/use":
            prefix = f"Local chat not found: {missing}." if missing else "Local chat not found."
            return f"{prefix}\nUse /threads to see available chats."
        if canonical == "/switch":
            prefix = f"Account not found: {missing}." if missing else "Account not found."
            return f"{prefix}\nUse /accounts to see available accounts."
        return "Requested item was not found.\nUse /help for available commands."

    @classmethod
    def _file_not_found_text(cls, command: str, _exc: FileNotFoundError) -> str:
        canonical = cls._resolve_command(command)
        if canonical == "/attachsession":
            return cls._invalid_argument_text(
                command="/attachsession",
                problem="Session source not found.",
            )
        if canonical in {"/clonevscode", "/deletevscodecopy", "/exportvscode", "/syncvscode"}:
            return "VSCode view copy not found.\nUse /clonevscode to create a fresh view."
        return "File or path not found.\nCheck the path and try again."

    @classmethod
    def _command_help_text(cls, raw_ref: str) -> str:
        target = raw_ref.strip().split(" ", 1)[0].strip().lower()
        if not target:
            return cls._help_text()
        if not target.startswith("/"):
            target = f"/{target}"
        canonical = cls._resolve_command(target)
        doc = cls._command_doc_map().get(canonical)
        if not isinstance(doc, dict):
            return (
                f"Command not found: {raw_ref}\n"
                "Use /help to list commands."
            )

        aliases = doc.get("aliases", ())
        alias_text = ", ".join(str(alias) for alias in aliases) if aliases else "-"
        lines = [
            f"Command: {canonical}",
            f"Purpose: {doc['summary']}",
            f"Usage: {doc['usage']}",
            f"Aliases: {alias_text}",
            f"Details: {doc['details']}",
        ]
        examples = doc.get("examples", ())
        if examples:
            lines.append("Examples:")
            for example in examples:
                lines.append(str(example))
        return "\n".join(lines)

    @classmethod
    def _telegram_command_hints(cls) -> list[dict[str, str]]:
        hints: list[dict[str, str]] = []
        seen: set[str] = set()
        for doc in cls._command_docs():
            raw_name = str(doc.get("menu") or str(doc["command"]).lstrip("/")).lower()
            command_name = raw_name.replace("-", "_")
            if command_name in seen:
                continue
            seen.add(command_name)
            hints.append(
                {
                    "command": command_name,
                    "description": str(doc["summary"])[:256],
                }
            )
        return hints

    @classmethod
    def _help_text(cls) -> str:
        lines = ["Commands (use /help <command> for mini docs):"]
        for doc in cls._command_docs():
            aliases = doc.get("aliases", ())
            alias_suffix = ""
            if aliases:
                alias_suffix = f" | aliases: {', '.join(str(alias) for alias in aliases)}"
            lines.append(f"{doc['command']} - {doc['summary']}{alias_suffix}")
        lines.extend(
            [
                "",
                "You can also use the Telegram keyboard buttons for quick actions.",
                "Plain text without a command is also sent to Codex.",
            ]
        )
        return "\n".join(lines)

    @classmethod
    def _start_text(cls) -> str:
        return (
            "Welcome. This bot lets you talk to local Codex from Telegram.\n\n"
            "Quick start:\n"
            "- Send any plain text message to run it as a Codex prompt\n"
            "- /newchat (or /new) to create a local chat\n"
            "- /threads (or /chats) to list local chats\n"
            "- /use <alias> (or /chat <alias>) to switch local chat\n"
            "- /status (or /state) to view current state\n"
            "- /help to open full command docs\n\n"
            "You can also use the keyboard buttons below for quick actions.\n"
            "Plain text without a command is also sent to Codex."
        )
