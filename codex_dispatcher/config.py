from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "quota exceeded",
    "try again later",
    "too many requests",
    "credits",
    "limit reached",
    "429",
)


@dataclass(frozen=True)
class AccountConfig:
    name: str
    auth_file: Path
    extra_files: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CodexConfig:
    binary: str
    cwd: Path
    state_dir: Path
    model: str | None
    extra_args: tuple[str, ...]
    cli_auth_credentials_store: str
    auto_switch_on_limit: bool
    response_timeout_seconds: int
    limit_markers: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    telegram_token: str
    allowed_chat_ids: tuple[int, ...]
    polling_timeout_seconds: int
    polling_retry_delay_seconds: int
    codex: CodexConfig
    accounts: tuple[AccountConfig, ...]
    config_path: Path


def _expand_path(raw_value: str | None, *, base_dir: Path | None = None) -> Path | None:
    if raw_value is None:
        return None
    path = Path(os.path.expandvars(raw_value)).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = (base_dir / path).resolve()
    return path


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Config field '{key}' must be a non-empty string.")
    return value.strip()


def load_config(path: str | None = None) -> AppConfig:
    config_path = _expand_path(path or os.environ.get("BOT_CONFIG", "config.json"))
    assert config_path is not None
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy config.example.json to config.json first."
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a JSON object.")

    base_dir = config_path.parent
    telegram_token = _require_string(raw, "telegram_token")

    allowed_chat_ids_raw = raw.get("allowed_chat_ids", [])
    if not isinstance(allowed_chat_ids_raw, list) or not all(
        isinstance(item, int) for item in allowed_chat_ids_raw
    ):
        raise ValueError("Config field 'allowed_chat_ids' must be a list of Telegram chat ids.")

    codex_raw = raw.get("codex")
    if not isinstance(codex_raw, dict):
        raise ValueError("Config field 'codex' must be an object.")

    codex = CodexConfig(
        binary=_require_string(codex_raw, "binary"),
        cwd=_expand_path(_require_string(codex_raw, "cwd"), base_dir=base_dir),
        state_dir=_expand_path(_require_string(codex_raw, "state_dir"), base_dir=base_dir),
        model=codex_raw.get("model") if isinstance(codex_raw.get("model"), str) else None,
        extra_args=tuple(arg for arg in codex_raw.get("extra_args", []) if isinstance(arg, str)),
        cli_auth_credentials_store=_require_string(codex_raw, "cli_auth_credentials_store"),
        auto_switch_on_limit=bool(codex_raw.get("auto_switch_on_limit", True)),
        response_timeout_seconds=int(codex_raw.get("response_timeout_seconds", 7200)),
        limit_markers=tuple(
            item for item in codex_raw.get("limit_markers", DEFAULT_LIMIT_MARKERS) if isinstance(item, str)
        )
        or DEFAULT_LIMIT_MARKERS,
    )

    accounts_raw = raw.get("accounts")
    if not isinstance(accounts_raw, list) or not accounts_raw:
        raise ValueError("Config field 'accounts' must be a non-empty list.")

    accounts: list[AccountConfig] = []
    seen_names: set[str] = set()
    for entry in accounts_raw:
        if not isinstance(entry, dict):
            raise ValueError("Each item in 'accounts' must be an object.")
        name = _require_string(entry, "name")
        if name in seen_names:
            raise ValueError(f"Duplicate account name: {name}")
        seen_names.add(name)
        auth_file = _expand_path(_require_string(entry, "auth_file"), base_dir=base_dir)
        extra_files_raw = entry.get("extra_files", [])
        if not isinstance(extra_files_raw, list):
            raise ValueError(f"'extra_files' for account {name} must be a list.")
        extra_files = tuple(
            _expand_path(item, base_dir=base_dir)
            for item in extra_files_raw
            if isinstance(item, str) and item.strip()
        )
        accounts.append(AccountConfig(name=name, auth_file=auth_file, extra_files=extra_files))

    return AppConfig(
        telegram_token=telegram_token,
        allowed_chat_ids=tuple(allowed_chat_ids_raw),
        polling_timeout_seconds=int(raw.get("polling_timeout_seconds", 25)),
        polling_retry_delay_seconds=int(raw.get("polling_retry_delay_seconds", 3)),
        codex=codex,
        accounts=tuple(accounts),
        config_path=config_path,
    )
