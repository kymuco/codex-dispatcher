from __future__ import annotations

import argparse

from . import __version__
from .bot import CodexTelegramBot
from .check_env import run_environment_check_from_path
from .config import load_config
from .core import StartupCheckError
from .sdk import Dispatcher


def _format_accounts_text(dispatcher: Dispatcher) -> str:
    lines = ["Accounts"]
    for account in dispatcher.accounts():
        marker = "active" if account.is_active else "idle"
        lines.append(f"- {account.name} [{marker}]")
    return "\n".join(lines)


def _format_status_text(dispatcher: Dispatcher, chat_id: int) -> str:
    snapshot = dispatcher.status(chat_id)
    busy = "yes" if snapshot.worker_busy else "no"
    return (
        "Status\n\n"
        f"Chat id: {chat_id}\n"
        f"Active local chat: {snapshot.active_alias}\n"
        f"Session: {snapshot.session}\n"
        f"Last account: {snapshot.last_account}\n\n"
        "Settings\n"
        f"Model: {snapshot.model}\n"
        f"Reasoning: {snapshot.reasoning}\n"
        f"Sandbox: {snapshot.sandbox}\n\n"
        "Runtime\n"
        f"Default account: {snapshot.default_account}\n"
        f"Queue: {snapshot.queue_size}\n"
        f"Worker busy: {busy}"
    )


def _format_health_text(dispatcher: Dispatcher, chat_id: int) -> str:
    snapshot = dispatcher.health(chat_id)
    busy = "yes" if snapshot.worker_busy else "no"
    return (
        "Health\n\n"
        f"Chat id: {chat_id}\n"
        f"Bot: {snapshot.bot_status}\n"
        f"Codex binary: {snapshot.codex_binary}\n"
        f"Workspace: {snapshot.workspace}\n"
        f"Accounts: {snapshot.accounts}\n\n"
        "Runtime\n"
        f"Default account: {snapshot.default_account}\n"
        f"Queue: {snapshot.queue_size}\n"
        f"Worker busy: {busy}\n\n"
        "Chat\n"
        f"Active local chat: {snapshot.active_alias}\n"
        f"Session: {snapshot.session}"
    )


def _format_threads_text(dispatcher: Dispatcher, chat_id: int) -> str:
    snapshot = dispatcher.threads(chat_id)
    lines = [f"Local chats ({len(snapshot.items)})", f"Chat id: {chat_id}", ""]
    for item in snapshot.items:
        marker = "active" if item.is_active else "idle"
        lines.append(f"[{marker}] {item.alias}")
        lines.append(f"Session: {item.session}")
        lines.append(f"Last account: {item.last_account}")
        lines.append("")
    return "\n".join(lines)


def _format_settings_text(dispatcher: Dispatcher, chat_id: int) -> str:
    snapshot = dispatcher.settings(chat_id)
    return (
        "Settings\n\n"
        f"Chat id: {chat_id}\n"
        f"Active local chat: {snapshot.active_alias}\n"
        f"Model: {snapshot.model}\n"
        f"Reasoning: {snapshot.reasoning}\n"
        f"Sandbox: {snapshot.sandbox}"
    )


def _format_session_id_text(dispatcher: Dispatcher, chat_id: int) -> str:
    snapshot = dispatcher.session_id(chat_id)
    lines = [
        "Session ID",
        "",
        f"Chat id: {chat_id}",
        f"Active local chat: {snapshot.active_alias}",
    ]
    if snapshot.session_id is None:
        lines.append("Session: not started")
    else:
        lines.append(f"Session id: {snapshot.session_id}")
    return "\n".join(lines)


def _run_sdk_cli_action(args: argparse.Namespace) -> int | None:
    if not any(
        (
            args.accounts,
            args.status_chat_id is not None,
            args.health_chat_id is not None,
            args.threads_chat_id is not None,
            args.settings_chat_id is not None,
            args.session_id_chat_id is not None,
        )
    ):
        return None

    dispatcher = Dispatcher.from_config(args.config)
    if args.accounts:
        print(_format_accounts_text(dispatcher))
        return 0
    if args.status_chat_id is not None:
        print(_format_status_text(dispatcher, args.status_chat_id))
        return 0
    if args.health_chat_id is not None:
        print(_format_health_text(dispatcher, args.health_chat_id))
        return 0
    if args.threads_chat_id is not None:
        print(_format_threads_text(dispatcher, args.threads_chat_id))
        return 0
    if args.settings_chat_id is not None:
        print(_format_settings_text(dispatcher, args.settings_chat_id))
        return 0
    if args.session_id_chat_id is not None:
        print(_format_session_id_text(dispatcher, args.session_id_chat_id))
        return 0
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Codex dispatcher.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run environment checks and exit.",
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--accounts",
        action="store_true",
        help="Print configured accounts and active default account from local state.",
    )
    action_group.add_argument(
        "--status-chat-id",
        type=int,
        metavar="CHAT_ID",
        help="Print status snapshot for chat id without starting Telegram polling.",
    )
    action_group.add_argument(
        "--health-chat-id",
        type=int,
        metavar="CHAT_ID",
        help="Print health snapshot for chat id without starting Telegram polling.",
    )
    action_group.add_argument(
        "--threads-chat-id",
        type=int,
        metavar="CHAT_ID",
        help="List local chats for chat id without starting Telegram polling.",
    )
    action_group.add_argument(
        "--settings-chat-id",
        type=int,
        metavar="CHAT_ID",
        help="Print active chat runtime settings for chat id without starting Telegram polling.",
    )
    action_group.add_argument(
        "--session-id-chat-id",
        type=int,
        metavar="CHAT_ID",
        help="Print active session id for chat id without starting Telegram polling.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to config.json. Defaults to BOT_CONFIG or ./config.json.",
    )
    args = parser.parse_args()

    if args.check:
        code, text = run_environment_check_from_path(args.config)
        print(text)
        raise SystemExit(code)

    action_exit_code = _run_sdk_cli_action(args)
    if action_exit_code is not None:
        raise SystemExit(action_exit_code)

    config = load_config(args.config)
    bot = CodexTelegramBot(config)
    try:
        bot.run_forever()
    except StartupCheckError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
