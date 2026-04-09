from __future__ import annotations

import shutil
from pathlib import Path

from .config import AccountConfig, AppConfig
from .state import StateStore


class AccountManager:
    def __init__(self, config: AppConfig, state: StateStore) -> None:
        self.config = config
        self.state = state
        self._accounts_by_name = {account.name: account for account in config.accounts}

    def list_account_names(self) -> list[str]:
        return [account.name for account in self.config.accounts]

    def get_account(self, name: str) -> AccountConfig:
        account = self._accounts_by_name.get(name)
        if account is None:
            raise KeyError(f"Unknown account: {name}")
        return account

    def get_active_account_name(self) -> str:
        active = self.state.get_active_account()
        if active and active in self._accounts_by_name:
            return active
        first = self.config.accounts[0].name
        self.state.set_active_account(first)
        return first

    def set_active_account(self, name: str) -> AccountConfig:
        account = self.get_account(name)
        self.state.set_active_account(account.name)
        return account

    def next_account_name(self, current_name: str, attempted: list[str] | None = None) -> str | None:
        names = self.list_account_names()
        if current_name not in names:
            return names[0] if names else None
        attempted_set = set(attempted or [])
        start_index = names.index(current_name)
        for offset in range(1, len(names) + 1):
            candidate = names[(start_index + offset) % len(names)]
            if candidate not in attempted_set:
                return candidate
        return None

    def _managed_filenames(self) -> set[str]:
        filenames = {"auth.json"}
        for account in self.config.accounts:
            for extra_file in account.extra_files:
                filenames.add(Path(extra_file).name)
        return filenames

    def prepare_account_files(self, name: str) -> AccountConfig:
        account = self.get_account(name)
        if not account.auth_file.exists():
            raise FileNotFoundError(f"auth.json not found for account '{name}': {account.auth_file}")

        state_dir = self.config.codex.state_dir
        state_dir.mkdir(parents=True, exist_ok=True)

        for filename in self._managed_filenames():
            target = state_dir / filename
            if target.exists():
                target.unlink()

        shutil.copy2(account.auth_file, state_dir / "auth.json")
        for extra_file in account.extra_files:
            extra_path = Path(extra_file)
            if not extra_path.exists():
                raise FileNotFoundError(
                    f"Extra file for account '{name}' not found: {extra_path}"
                )
            shutil.copy2(extra_path, state_dir / extra_path.name)

        self.state.set_active_account(name)
        return account
