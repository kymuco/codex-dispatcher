from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_dispatcher.check_env import (
    format_environment_report,
    run_environment_check,
    run_environment_check_from_path,
)
from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig
from codex_dispatcher.diagnostics import startup_report


class EnvironmentCheckTests(unittest.TestCase):
    def _make_config(self, temp_dir: Path, *, token: str = "123456:abcdef") -> AppConfig:
        auth_file = temp_dir / "auth.json"
        auth_file.write_text("{}", encoding="utf-8")
        return AppConfig(
            telegram_token=token,
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
            accounts=(AccountConfig(name="acc1", auth_file=auth_file),),
            config_path=temp_dir / "config.json",
        )

    def test_startup_report_ready_when_environment_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            config = self._make_config(Path(temp_dir_name))
            report = startup_report(config)

            self.assertTrue(report["ready"])
            self.assertEqual(report["token"], "ok")
            self.assertEqual(report["codex_binary"], "ok")
            self.assertEqual(report["workspace"], "ok")
            self.assertEqual(report["state_dir"], "ok")
            self.assertEqual(report["accounts"], "ok")
            self.assertEqual(report["issues"], [])

    def test_startup_report_detects_placeholder_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            config = self._make_config(Path(temp_dir_name), token="<telegram-bot-token>")
            report = startup_report(config)
            text = format_environment_report(report, config_path=config.config_path)

            self.assertFalse(report["ready"])
            self.assertEqual(report["token"], "missing")
            self.assertIn("Telegram token looks invalid or placeholder.", text)
            self.assertIn("Result: not ready", text)

    def test_run_environment_check_from_path_handles_missing_config(self) -> None:
        code, text = run_environment_check_from_path("C:\\missing\\config.json")
        self.assertEqual(code, 1)
        self.assertIn("Environment check failed.", text)
        self.assertIn("Problem:", text)
        self.assertIn("Fix:", text)

    def test_run_environment_check_from_path_handles_invalid_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config_path = temp_dir / "config.json"
            config_path.write_text("{}", encoding="utf-8")

            code, text = run_environment_check_from_path(str(config_path))

            self.assertEqual(code, 1)
            self.assertIn("Environment check failed.", text)
            self.assertIn("Config field 'telegram_token' must be a non-empty string.", text)
            self.assertIn("Fix: Update the listed config field and run --check again.", text)

    def test_run_environment_check_from_path_reports_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            auth_file = temp_dir / "auth.json"
            auth_file.write_text("{}", encoding="utf-8")
            config_path = temp_dir / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "telegram_token": "<telegram-bot-token>",
                        "allowed_chat_ids": [],
                        "codex": {
                            "binary": sys.executable,
                            "cwd": str(temp_dir),
                            "state_dir": str(temp_dir / "state"),
                            "cli_auth_credentials_store": "file",
                        },
                        "accounts": [{"name": "acc1", "auth_file": str(auth_file)}],
                    }
                ),
                encoding="utf-8",
            )

            code, text = run_environment_check_from_path(str(config_path))
            self.assertEqual(code, 1)
            self.assertIn("Telegram token: missing", text)
            self.assertIn("Result: not ready", text)

    def test_run_environment_check_uses_dispatcher_service_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            config = self._make_config(Path(temp_dir_name))
            fake_report = {
                "ready": True,
                "issues": [],
                "token": "ok",
                "codex_binary": "ok",
                "workspace": "ok",
                "state_dir": "ok",
                "accounts": "ok",
            }

            with patch("codex_dispatcher.check_env.DispatcherService") as dispatcher_cls:
                dispatcher = dispatcher_cls.return_value
                dispatcher.startup_report.return_value = fake_report

                code, text = run_environment_check(config)

            dispatcher_cls.assert_called_once_with(config)
            dispatcher.startup_report.assert_called_once_with()
            self.assertEqual(code, 0)
            self.assertIn("Environment check", text)
            self.assertIn("Result: ready", text)

    def test_startup_report_auth_file_issue_includes_path_and_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            auth_path = config.accounts[0].auth_file
            auth_path.unlink()

            report = startup_report(config)
            issue_text = "\n".join(str(item) for item in report["issues"])

            self.assertFalse(report["ready"])
            self.assertIn("auth_file is missing", issue_text)
            self.assertIn(str(auth_path), issue_text)
            self.assertIn("Fix:", issue_text)


if __name__ == "__main__":
    unittest.main()
