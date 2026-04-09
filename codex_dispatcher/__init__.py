"""Telegram dispatcher for local Codex account orchestration."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as metadata_version


_PACKAGE_NAME = "codex-dispatcher"
_DEFAULT_VERSION = "0.0.0+local"


def get_version() -> str:
    """Return installed package version, with a local fallback for source runs."""
    try:
        return metadata_version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return _DEFAULT_VERSION


__version__ = get_version()
