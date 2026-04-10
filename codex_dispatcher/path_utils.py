from __future__ import annotations

from pathlib import Path


WINDOWS_EXTENDED_PREFIX = "\\\\?\\"
WINDOWS_UNC_EXTENDED_PREFIX = "\\\\?\\UNC\\"


def strip_windows_extended_prefix(raw_path: str) -> str:
    if raw_path.startswith(WINDOWS_UNC_EXTENDED_PREFIX):
        return "\\\\" + raw_path[len(WINDOWS_UNC_EXTENDED_PREFIX) :]
    if raw_path.startswith(WINDOWS_EXTENDED_PREFIX):
        return raw_path[len(WINDOWS_EXTENDED_PREFIX) :]
    return raw_path


def ensure_windows_extended_prefix(raw_path: str) -> str:
    normalized = strip_windows_extended_prefix(raw_path).replace("/", "\\")
    if normalized.startswith("\\\\"):
        unc_tail = normalized.lstrip("\\")
        return f"{WINDOWS_UNC_EXTENDED_PREFIX}{unc_tail}"
    if len(normalized) >= 2 and normalized[1] == ":":
        drive = normalized[0].upper()
        return f"{WINDOWS_EXTENDED_PREFIX}{drive}{normalized[1:]}"
    return normalized


def normalize_rollout_path(path: Path) -> str:
    raw = str(path.resolve())
    if raw.startswith("\\\\") or (len(raw) >= 2 and raw[1] == ":"):
        return ensure_windows_extended_prefix(raw)
    return raw


def display_path(value: Path | str) -> str:
    raw = str(value)
    return strip_windows_extended_prefix(raw)
