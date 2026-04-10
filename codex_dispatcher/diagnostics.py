from __future__ import annotations

from typing import Any

from .config import AppConfig
from .codex_runner import CodexService


def startup_report(config: AppConfig) -> dict[str, Any]:
    issues: list[str] = []
    token_status = "ok"
    codex_binary_status = "ok"
    workspace_status = "ok"
    state_dir_status = "ok"
    accounts_status = "ok"

    token = config.telegram_token.strip()
    if (
        not token
        or "replace-with-your-bot-token" in token.lower()
        or token.startswith("<")
        or ":" not in token
    ):
        token_status = "missing"
        issues.append(
            "Telegram token looks invalid or placeholder.\n"
            "Set telegram_token in config.json to a real bot token."
        )

    try:
        CodexService._resolve_binary_path(config.codex.binary)
    except FileNotFoundError:
        codex_binary_status = "missing"
        issues.append(
            "Codex binary was not found.\n"
            "Set codex.binary in config.json to a valid executable path."
        )

    cwd = config.codex.cwd
    if not cwd.exists() or not cwd.is_dir():
        workspace_status = "missing"
        issues.append(
            f"Workspace directory is missing: {cwd}\n"
            "Set codex.cwd in config.json to an existing directory."
        )

    try:
        config.codex.state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        state_dir_status = "error"
        issues.append(
            f"State directory is not writable: {config.codex.state_dir}\n"
            "Set codex.state_dir in config.json to a writable path."
        )

    if not config.accounts:
        accounts_status = "missing"
        issues.append(
            "No Codex accounts are configured.\n"
            "Add at least one account in config.json."
        )
    else:
        for account in config.accounts:
            if not account.auth_file.exists():
                accounts_status = "missing"
                issues.append(
                    f"account '{account.name}' auth file is missing.\n"
                    "Check the auth_file path in config.json."
                )
                break
            missing_extra = next((path for path in account.extra_files if not path.exists()), None)
            if missing_extra is not None:
                accounts_status = "missing"
                issues.append(
                    f"account '{account.name}' extra file is missing: {missing_extra}\n"
                    "Check account extra_files paths in config.json."
                )
                break

    return {
        "ready": not issues,
        "issues": issues,
        "token": token_status,
        "codex_binary": codex_binary_status,
        "workspace": workspace_status,
        "state_dir": state_dir_status,
        "accounts": accounts_status,
    }
