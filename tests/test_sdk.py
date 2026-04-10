from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_dispatcher.codex_runner import CodexRunResult
from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig
from codex_dispatcher.sdk import Dispatcher


class DispatcherSdkTests(unittest.TestCase):
    def _make_config(self, temp_dir: Path) -> AppConfig:
        auth1 = temp_dir / "acc1.json"
        auth2 = temp_dir / "acc2.json"
        auth1.write_text("{}", encoding="utf-8")
        auth2.write_text("{}", encoding="utf-8")
        return AppConfig(
            telegram_token="123456:abc",
            allowed_chat_ids=(),
            polling_timeout_seconds=10,
            polling_retry_delay_seconds=1,
            codex=CodexConfig(
                binary=sys.executable,
                cwd=temp_dir,
                state_dir=temp_dir / "bot-home",
                model=None,
                extra_args=("--skip-git-repo-check",),
                cli_auth_credentials_store="file",
                auto_switch_on_limit=True,
                response_timeout_seconds=10,
                limit_markers=("usage limit",),
            ),
            accounts=(
                AccountConfig(name="acc1", auth_file=auth1),
                AccountConfig(name="acc2", auth_file=auth2),
            ),
            config_path=temp_dir / "config.json",
        )

    def test_from_config_loads_and_check_uses_shared_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            auth_file = temp_dir / "auth.json"
            auth_file.write_text("{}", encoding="utf-8")
            config_path = temp_dir / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "telegram_token": "123456:abc",
                        "allowed_chat_ids": [],
                        "codex": {
                            "binary": sys.executable,
                            "cwd": str(temp_dir),
                            "state_dir": str(temp_dir / "bot-home"),
                            "cli_auth_credentials_store": "file",
                        },
                        "accounts": [{"name": "acc1", "auth_file": str(auth_file)}],
                    }
                ),
                encoding="utf-8",
            )

            dispatcher = Dispatcher.from_config(config_path)
            with patch("codex_dispatcher.sdk.dispatcher.run_environment_check", return_value=(0, "Environment check")) as check_mock:
                code, text = dispatcher.check()

            check_mock.assert_called_once_with(dispatcher.config)
            self.assertEqual(code, 0)
            self.assertEqual(text, "Environment check")

    def test_chat_and_settings_methods_use_active_alias_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            dispatcher = Dispatcher(self._make_config(Path(temp_dir_name)))
            chat_id = 7001

            with (
                patch.object(dispatcher._service, "get_active_alias", return_value="bugfix") as get_alias,
                patch.object(dispatcher._service, "set_model") as set_model,
                patch.object(dispatcher._service, "set_reasoning") as set_reasoning,
                patch.object(dispatcher._service, "set_sandbox") as set_sandbox,
            ):
                dispatcher.set_model(chat_id, "gpt-5.4")
                dispatcher.set_reasoning(chat_id, "high")
                dispatcher.set_sandbox(chat_id, "workspace-write")

            self.assertEqual(get_alias.call_count, 3)
            set_model.assert_called_once_with(chat_id, "bugfix", "gpt-5.4")
            set_reasoning.assert_called_once_with(chat_id, "bugfix", "high")
            set_sandbox.assert_called_once_with(chat_id, "bugfix", "workspace-write")

    def test_ask_runs_startup_checks_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            dispatcher = Dispatcher(self._make_config(Path(temp_dir_name)))
            expected = CodexRunResult(
                success=True,
                limit_detected=False,
                returncode=0,
                account_name="acc1",
                session_id="session-1",
                final_message="Done",
                stdout="",
                stderr="",
            )

            with (
                patch.object(dispatcher._service, "run_startup_checks") as ready_check,
                patch.object(dispatcher._service, "get_active_alias", return_value="main") as get_alias,
                patch.object(dispatcher._service, "run_prompt", return_value=expected) as run_prompt,
            ):
                result = dispatcher.ask(7002, "summarize tests")

            ready_check.assert_called_once_with()
            get_alias.assert_called_once_with(7002)
            run_prompt.assert_called_once_with(
                chat_id=7002,
                alias="main",
                prompt="summarize tests",
            )
            self.assertIs(result, expected)

    def test_ask_rejects_empty_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            dispatcher = Dispatcher(self._make_config(Path(temp_dir_name)))
            with self.assertRaisesRegex(ValueError, "Prompt must not be empty."):
                dispatcher.ask(7003, "   ")


if __name__ == "__main__":
    unittest.main()
