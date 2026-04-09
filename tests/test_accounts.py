from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.accounts import AccountManager
from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig
from codex_dispatcher.state import StateStore


class AccountManagerTests(unittest.TestCase):
    def test_prepare_account_files_copies_auth_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            auth_source = temp_dir / "source-auth.json"
            auth_source.write_text('{"access_token":"abc"}', encoding="utf-8")

            config = AppConfig(
                telegram_token="token",
                allowed_chat_ids=(),
                polling_timeout_seconds=10,
                polling_retry_delay_seconds=1,
                codex=CodexConfig(
                    binary="codex",
                    cwd=temp_dir,
                    state_dir=temp_dir / "state",
                    model=None,
                    extra_args=("--skip-git-repo-check",),
                    cli_auth_credentials_store="file",
                    auto_switch_on_limit=True,
                    response_timeout_seconds=10,
                    limit_markers=("usage limit",),
                ),
                accounts=(AccountConfig(name="acc1", auth_file=auth_source),),
                config_path=temp_dir / "config.json",
            )
            state = StateStore(temp_dir / "bot_state.json")
            manager = AccountManager(config, state)

            manager.prepare_account_files("acc1")

            copied = (config.codex.state_dir / "auth.json").read_text(encoding="utf-8")
            self.assertEqual(copied, '{"access_token":"abc"}')
            self.assertEqual(state.get_active_account(), "acc1")

    def test_next_account_skips_attempted_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            for index in range(1, 4):
                (temp_dir / f"acc{index}.json").write_text("{}", encoding="utf-8")

            config = AppConfig(
                telegram_token="token",
                allowed_chat_ids=(),
                polling_timeout_seconds=10,
                polling_retry_delay_seconds=1,
                codex=CodexConfig(
                    binary="codex",
                    cwd=temp_dir,
                    state_dir=temp_dir / "state",
                    model=None,
                    extra_args=("--skip-git-repo-check",),
                    cli_auth_credentials_store="file",
                    auto_switch_on_limit=True,
                    response_timeout_seconds=10,
                    limit_markers=("usage limit",),
                ),
                accounts=(
                    AccountConfig(name="acc1", auth_file=temp_dir / "acc1.json"),
                    AccountConfig(name="acc2", auth_file=temp_dir / "acc2.json"),
                    AccountConfig(name="acc3", auth_file=temp_dir / "acc3.json"),
                ),
                config_path=temp_dir / "config.json",
            )
            state = StateStore(temp_dir / "bot_state.json")
            manager = AccountManager(config, state)

            self.assertEqual(manager.next_account_name("acc1", attempted=["acc1"]), "acc2")
            self.assertEqual(manager.next_account_name("acc1", attempted=["acc1", "acc2"]), "acc3")
            self.assertIsNone(manager.next_account_name("acc1", attempted=["acc1", "acc2", "acc3"]))

    def test_prepare_account_files_cleans_stale_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            auth1 = temp_dir / "acc1.json"
            auth2 = temp_dir / "acc2.json"
            extra = temp_dir / "cap_sid"
            auth1.write_text('{"access_token":"one"}', encoding="utf-8")
            auth2.write_text('{"access_token":"two"}', encoding="utf-8")
            extra.write_text("sid-1", encoding="utf-8")

            config = AppConfig(
                telegram_token="token",
                allowed_chat_ids=(),
                polling_timeout_seconds=10,
                polling_retry_delay_seconds=1,
                codex=CodexConfig(
                    binary="codex",
                    cwd=temp_dir,
                    state_dir=temp_dir / "state",
                    model=None,
                    extra_args=("--skip-git-repo-check",),
                    cli_auth_credentials_store="file",
                    auto_switch_on_limit=True,
                    response_timeout_seconds=10,
                    limit_markers=("usage limit",),
                ),
                accounts=(
                    AccountConfig(name="acc1", auth_file=auth1, extra_files=(extra,)),
                    AccountConfig(name="acc2", auth_file=auth2),
                ),
                config_path=temp_dir / "config.json",
            )
            state = StateStore(temp_dir / "bot_state.json")
            manager = AccountManager(config, state)

            manager.prepare_account_files("acc1")
            self.assertTrue((config.codex.state_dir / "cap_sid").exists())

            manager.prepare_account_files("acc2")
            self.assertFalse((config.codex.state_dir / "cap_sid").exists())


if __name__ == "__main__":
    unittest.main()
