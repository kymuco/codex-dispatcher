from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace
from unittest.mock import patch

import codex_dispatcher.__main__ as cli
from codex_dispatcher import __version__, get_version


class CliTests(unittest.TestCase):
    def test_get_version_uses_fallback_when_metadata_missing(self) -> None:
        with patch("codex_dispatcher.metadata_version", side_effect=PackageNotFoundError):
            self.assertEqual(get_version(), "0.0.0+local")

    def test_main_prints_version_and_exits(self) -> None:
        output = io.StringIO()

        with patch("sys.argv", ["codex-dispatcher", "--version"]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(result.exception.code, 0)
        self.assertIn(__version__, output.getvalue())

    def test_main_check_mode_exits_with_report_code(self) -> None:
        output = io.StringIO()
        with (
            patch("codex_dispatcher.__main__.run_environment_check_from_path", return_value=(0, "Environment check")),
            patch("sys.argv", ["codex-dispatcher", "--check"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(result.exception.code, 0)
        self.assertIn("Environment check", output.getvalue())

    def test_main_accounts_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        fake_dispatcher = SimpleNamespace(
            accounts=lambda: (
                SimpleNamespace(name="acc1", is_active=True),
                SimpleNamespace(name="acc2", is_active=False),
            )
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "--accounts"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Accounts", text)
        self.assertIn("- acc1 [active]", text)
        self.assertIn("- acc2 [idle]", text)

    def test_main_status_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        fake_status = SimpleNamespace(
            active_alias="bugfix",
            session="started",
            last_account="acc2",
            model="gpt-5.4",
            reasoning="high",
            sandbox="workspace-write",
            default_account="acc2",
            queue_size=1,
            worker_busy=True,
        )
        fake_dispatcher = SimpleNamespace(status=lambda chat_id: fake_status)
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "--status-chat-id", "12345"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Status", text)
        self.assertIn("Chat id: 12345", text)
        self.assertIn("Active local chat: bugfix", text)
        self.assertIn("Worker busy: yes", text)

    def test_main_switch_account_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        switch_calls: list[str] = []
        fake_dispatcher = SimpleNamespace(
            switch_account=lambda name: switch_calls.append(name),
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "--switch-account", "acc2"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(switch_calls, ["acc2"])
        self.assertIn("Default account changed: acc2", output.getvalue())

    def test_main_new_chat_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        new_chat_calls: list[tuple[int, str]] = []
        fake_dispatcher = SimpleNamespace(
            new_chat=lambda chat_id, alias: new_chat_calls.append((chat_id, alias)) or alias,
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "--new-chat", "3456", "bugfix"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(new_chat_calls, [(3456, "bugfix")])
        text = output.getvalue()
        self.assertIn("Local chat created and activated.", text)
        self.assertIn("Chat id: 3456", text)
        self.assertIn("Alias: bugfix", text)

    def test_main_set_model_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        set_model_calls: list[tuple[int, str | None]] = []
        active_chat_calls: list[int] = []
        fake_dispatcher = SimpleNamespace(
            set_model=lambda chat_id, model: set_model_calls.append((chat_id, model)),
            active_chat=lambda chat_id: active_chat_calls.append(chat_id) or "main",
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "--set-model", "555", "default"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(set_model_calls, [(555, None)])
        self.assertEqual(active_chat_calls, [555])
        self.assertIn("Model: default", output.getvalue())

    def test_main_set_reasoning_rejects_invalid_value(self) -> None:
        with patch("sys.argv", ["codex-dispatcher", "--set-reasoning", "100", "turbo"]):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(
            str(result.exception),
            "Reasoning must be one of: low, medium, high, xhigh, default.",
        )


if __name__ == "__main__":
    unittest.main()
