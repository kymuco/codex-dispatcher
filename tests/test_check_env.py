from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.check_env import format_environment_report, run_environment_check_from_path
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
        self.assertIn("Environment check failed:", text)

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


if __name__ == "__main__":
    unittest.main()
