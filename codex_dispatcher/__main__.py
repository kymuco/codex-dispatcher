from __future__ import annotations

import argparse

from . import __version__
from .bot import CodexTelegramBot
from .check_env import run_environment_check_from_path
from .config import load_config
from .core import StartupCheckError
from .sdk import Dispatcher


def _parse_chat_id(raw_value: str, *, option: str) -> int:
    value = raw_value.strip()
    if not value:
        raise ValueError(f"{option} requires a chat id.")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{option} chat id must be an integer: {raw_value}") from exc


def _parse_optional_setting_value(raw_value: str) -> str | None:
    value = raw_value.strip()
    if not value:
        raise ValueError("Setting value must not be empty.")
    if value.lower() in {"default", "clear", "none", "off"}:
        return None
    return value


def _parse_reasoning_value(raw_value: str) -> str | None:
    value = _parse_optional_setting_value(raw_value)
    if value is None:
        return None
    normalized = value.lower()
    if normalized not in {"low", "medium", "high", "xhigh"}:
        raise ValueError(
            "Reasoning must be one of: low, medium, high, xhigh, default."
        )
    return normalized


def _parse_sandbox_value(raw_value: str) -> str | None:
    value = _parse_optional_setting_value(raw_value)
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {"read-only", "read", "readonly"}:
        return "read-only"
    if normalized in {"workspace-write", "write"}:
        return "workspace-write"
    if normalized in {"danger-full-access", "danger", "full"}:
        return "danger-full-access"
    raise ValueError(
        "Sandbox must be one of: read-only, workspace-write, danger-full-access, default."
    )


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


def _format_attachment_text(chat_id: int, attachment: object) -> str:
    imported = bool(getattr(attachment, "imported", False))
    rekeyed = bool(getattr(attachment, "rekeyed", False))
    mode = "imported" if imported else "linked"
    return (
        "Session attached.\n"
        f"Chat id: {chat_id}\n"
        f"Source session id: {getattr(attachment, 'source_session_id', '-')}\n"
        f"Local session id: {getattr(attachment, 'session_id', '-')}\n"
        f"Mode: {mode}\n"
        f"Rekeyed: {'yes' if rekeyed else 'no'}\n"
        f"Stored at: {getattr(attachment, 'target_file', '-')}"
    )


def _format_vscode_export_text(action: str, chat_id: int, export: object) -> str:
    return (
        f"{action}\n"
        f"Chat id: {chat_id}\n"
        f"Session id: {getattr(export, 'session_id', '-')}\n"
        f"Result: {getattr(export, 'action', '-')}\n"
        f"Stored at: {getattr(export, 'target_file', '-')}"
    )


def _format_vscode_clone_text(chat_id: int, clone: object) -> str:
    return (
        "VSCode view copy created.\n"
        f"Chat id: {chat_id}\n"
        f"Source session id: {getattr(clone, 'source_session_id', '-')}\n"
        f"Cloned session id: {getattr(clone, 'cloned_session_id', '-')}\n"
        f"Thread name: {getattr(clone, 'thread_name', '-')}\n"
        f"Rollout path: {getattr(clone, 'target_file', '-')}"
    )


def _format_ask_result(chat_id: int, result: object) -> str:
    success = bool(getattr(result, "success", False))
    final_message = str(getattr(result, "final_message", "")).strip()
    if success:
        return (
            "Prompt completed.\n"
            f"Chat id: {chat_id}\n\n"
            f"{final_message}"
        )
    return (
        "Prompt failed.\n"
        f"Chat id: {chat_id}\n"
        f"Account: {getattr(result, 'account_name', '-')}\n"
        f"Return code: {getattr(result, 'returncode', '-')}\n\n"
        f"{final_message}"
    )


def _run_sdk_cli_action(args: argparse.Namespace) -> int | None:
    if not any(
        (
            args.accounts,
            args.status_chat_id is not None,
            args.health_chat_id is not None,
            args.threads_chat_id is not None,
            args.settings_chat_id is not None,
            args.session_id_chat_id is not None,
            args.switch_account is not None,
            args.new_chat is not None,
            args.use_chat is not None,
            args.reset_chat is not None,
            args.set_model is not None,
            args.set_reasoning is not None,
            args.set_sandbox is not None,
            args.attach_session is not None,
            args.export_vscode is not None,
            args.sync_vscode is not None,
            args.clone_vscode is not None,
            args.delete_vscode_copy is not None,
            args.ask is not None,
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
    if args.switch_account is not None:
        account = args.switch_account.strip()
        if not account:
            raise ValueError("--switch-account requires a non-empty account name.")
        dispatcher.switch_account(account)
        print(f"Default account changed: {account}")
        return 0
    if args.new_chat is not None:
        chat_id = _parse_chat_id(args.new_chat[0], option="--new-chat")
        alias = args.new_chat[1].strip()
        if not alias:
            raise ValueError("--new-chat requires a non-empty alias.")
        dispatcher.new_chat(chat_id, alias)
        print(
            "Local chat created and activated.\n"
            f"Chat id: {chat_id}\n"
            f"Alias: {alias}"
        )
        return 0
    if args.use_chat is not None:
        chat_id = _parse_chat_id(args.use_chat[0], option="--use-chat")
        alias = args.use_chat[1].strip()
        if not alias:
            raise ValueError("--use-chat requires a non-empty alias.")
        dispatcher.use_chat(chat_id, alias)
        print(
            "Active local chat changed.\n"
            f"Chat id: {chat_id}\n"
            f"Alias: {alias}"
        )
        return 0
    if args.reset_chat is not None:
        alias = dispatcher.reset_chat(args.reset_chat)
        print(
            "Session reset.\n"
            f"Chat id: {args.reset_chat}\n"
            f"Alias: {alias}"
        )
        return 0
    if args.set_model is not None:
        chat_id = _parse_chat_id(args.set_model[0], option="--set-model")
        model = _parse_optional_setting_value(args.set_model[1])
        dispatcher.set_model(chat_id, model)
        active_alias = dispatcher.active_chat(chat_id)
        print(
            "Model updated.\n"
            f"Chat id: {chat_id}\n"
            f"Alias: {active_alias}\n"
            f"Model: {model or 'default'}"
        )
        return 0
    if args.set_reasoning is not None:
        chat_id = _parse_chat_id(args.set_reasoning[0], option="--set-reasoning")
        reasoning = _parse_reasoning_value(args.set_reasoning[1])
        dispatcher.set_reasoning(chat_id, reasoning)
        active_alias = dispatcher.active_chat(chat_id)
        print(
            "Reasoning updated.\n"
            f"Chat id: {chat_id}\n"
            f"Alias: {active_alias}\n"
            f"Reasoning: {reasoning or 'default'}"
        )
        return 0
    if args.set_sandbox is not None:
        chat_id = _parse_chat_id(args.set_sandbox[0], option="--set-sandbox")
        sandbox = _parse_sandbox_value(args.set_sandbox[1])
        dispatcher.set_sandbox(chat_id, sandbox)
        active_alias = dispatcher.active_chat(chat_id)
        print(
            "Sandbox updated.\n"
            f"Chat id: {chat_id}\n"
            f"Alias: {active_alias}\n"
            f"Sandbox: {sandbox or 'default'}"
        )
        return 0
    if args.attach_session is not None:
        chat_id = _parse_chat_id(args.attach_session[0], option="--attach-session")
        session_ref = args.attach_session[1].strip()
        if not session_ref:
            raise ValueError("--attach-session requires a non-empty session reference.")
        attachment = dispatcher.attach_session(chat_id, session_ref)
        print(_format_attachment_text(chat_id, attachment))
        return 0
    if args.export_vscode is not None:
        export = dispatcher.export_vscode(args.export_vscode)
        print(_format_vscode_export_text("Session exported to VSCode.", args.export_vscode, export))
        return 0
    if args.sync_vscode is not None:
        export = dispatcher.sync_vscode(args.sync_vscode)
        print(_format_vscode_export_text("Session synced to VSCode.", args.sync_vscode, export))
        return 0
    if args.clone_vscode is not None:
        clone = dispatcher.clone_vscode(args.clone_vscode)
        print(_format_vscode_clone_text(args.clone_vscode, clone))
        return 0
    if args.delete_vscode_copy is not None:
        session_id = args.delete_vscode_copy.strip()
        if not session_id:
            raise ValueError("--delete-vscode-copy requires a non-empty session id.")
        deleted_path = dispatcher.delete_vscode_copy(session_id)
        print(
            "VSCode view copy deleted.\n"
            f"Session id: {session_id}\n"
            f"Rollout path: {deleted_path}"
        )
        return 0
    if args.ask is not None:
        chat_id = _parse_chat_id(args.ask[0], option="--ask")
        prompt = args.ask[1].strip()
        if not prompt:
            raise ValueError("--ask requires a non-empty prompt.")
        result = dispatcher.ask(chat_id, prompt)
        print(_format_ask_result(chat_id, result))
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
    action_group.add_argument(
        "--switch-account",
        metavar="ACCOUNT",
        help="Set default account in local bot state via SDK.",
    )
    action_group.add_argument(
        "--new-chat",
        nargs=2,
        metavar=("CHAT_ID", "ALIAS"),
        help="Create and activate a local chat alias for chat id via SDK.",
    )
    action_group.add_argument(
        "--use-chat",
        nargs=2,
        metavar=("CHAT_ID", "ALIAS"),
        help="Switch active local chat alias for chat id via SDK.",
    )
    action_group.add_argument(
        "--reset-chat",
        type=int,
        metavar="CHAT_ID",
        help="Reset active local chat session id for chat id via SDK.",
    )
    action_group.add_argument(
        "--set-model",
        nargs=2,
        metavar=("CHAT_ID", "MODEL"),
        help="Set model override for active local chat in chat id via SDK (use default to clear).",
    )
    action_group.add_argument(
        "--set-reasoning",
        nargs=2,
        metavar=("CHAT_ID", "LEVEL"),
        help="Set reasoning for active local chat in chat id via SDK (low|medium|high|xhigh|default).",
    )
    action_group.add_argument(
        "--set-sandbox",
        nargs=2,
        metavar=("CHAT_ID", "MODE"),
        help="Set sandbox mode for active local chat in chat id via SDK (read-only|workspace-write|danger-full-access|default).",
    )
    action_group.add_argument(
        "--attach-session",
        nargs=2,
        metavar=("CHAT_ID", "SESSION_REF"),
        help="Attach existing session id or rollout file to active local chat in chat id via SDK.",
    )
    action_group.add_argument(
        "--export-vscode",
        type=int,
        metavar="CHAT_ID",
        help="Export active local chat session to VSCode home for chat id via SDK.",
    )
    action_group.add_argument(
        "--sync-vscode",
        type=int,
        metavar="CHAT_ID",
        help="Sync active local chat session into VSCode home for chat id via SDK.",
    )
    action_group.add_argument(
        "--clone-vscode",
        type=int,
        metavar="CHAT_ID",
        help="Clone active local chat session into temporary VSCode view copy for chat id via SDK.",
    )
    action_group.add_argument(
        "--delete-vscode-copy",
        metavar="SESSION_ID",
        help="Delete temporary VSCode view copy by cloned session id via SDK.",
    )
    action_group.add_argument(
        "--ask",
        nargs=2,
        metavar=("CHAT_ID", "PROMPT"),
        help="Run prompt in active local chat for chat id via SDK.",
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

    try:
        action_exit_code = _run_sdk_cli_action(args)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
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
