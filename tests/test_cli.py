from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import codex_dispatcher.__main__ as cli
from codex_dispatcher import __version__, get_version


class CliTests(unittest.TestCase):
    def test_pyproject_exposes_cdx_script(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        pyproject_text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('cdx = "codex_dispatcher.__main__:main"', pyproject_text)

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

    def test_main_attach_session_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        attach_calls: list[tuple[int, str]] = []
        fake_attachment = SimpleNamespace(
            source_session_id="source-1",
            session_id="local-1",
            target_file=Path("C:/tmp/rollout-local-1.jsonl"),
            imported=True,
            rekeyed=True,
        )
        fake_dispatcher = SimpleNamespace(
            attach_session=lambda chat_id, session_ref: attach_calls.append((chat_id, session_ref)) or fake_attachment,
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "--attach-session", "777", "source-1"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(attach_calls, [(777, "source-1")])
        text = output.getvalue()
        self.assertIn("Session attached.", text)
        self.assertIn("Mode: imported", text)
        self.assertIn("Rekeyed: yes", text)

    def test_main_export_vscode_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        export_calls: list[int] = []
        fake_export = SimpleNamespace(
            session_id="s-123",
            action="created",
            target_file=Path("C:/tmp/export.jsonl"),
        )
        fake_dispatcher = SimpleNamespace(
            export_vscode=lambda chat_id: export_calls.append(chat_id) or fake_export,
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher),
            patch("sys.argv", ["codex-dispatcher", "--export-vscode", "900"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(result.exception.code, 0)
        self.assertEqual(export_calls, [900])
        text = output.getvalue()
        self.assertIn("Session exported to VSCode.", text)
        self.assertIn("Result: created", text)

    def test_main_clone_and_delete_vscode_modes_exit_with_zero(self) -> None:
        clone_output = io.StringIO()
        delete_output = io.StringIO()
        clone_calls: list[int] = []
        delete_calls: list[str] = []
        fake_clone = SimpleNamespace(
            source_session_id="source-2",
            cloned_session_id="clone-2",
            thread_name="TEMP VIEW - main",
            target_file=Path("C:/tmp/clone.jsonl"),
        )
        fake_dispatcher = SimpleNamespace(
            clone_vscode=lambda chat_id: clone_calls.append(chat_id) or fake_clone,
            delete_vscode_copy=lambda session_id: delete_calls.append(session_id) or Path("C:/tmp/clone.jsonl"),
        )

        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher),
            patch("sys.argv", ["codex-dispatcher", "--clone-vscode", "901"]),
            redirect_stdout(clone_output),
        ):
            with self.assertRaises(SystemExit) as clone_result:
                cli.main()

        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher),
            patch("sys.argv", ["codex-dispatcher", "--delete-vscode-copy", "clone-2"]),
            redirect_stdout(delete_output),
        ):
            with self.assertRaises(SystemExit) as delete_result:
                cli.main()

        self.assertEqual(clone_result.exception.code, 0)
        self.assertEqual(delete_result.exception.code, 0)
        self.assertEqual(clone_calls, [901])
        self.assertEqual(delete_calls, ["clone-2"])
        self.assertIn("VSCode view copy created.", clone_output.getvalue())
        self.assertIn("VSCode view copy deleted.", delete_output.getvalue())

    def test_main_ask_mode_exits_with_zero(self) -> None:
        output = io.StringIO()
        ask_calls: list[tuple[int, str]] = []
        fake_result = SimpleNamespace(
            success=True,
            final_message="Summary complete.",
        )
        fake_dispatcher = SimpleNamespace(
            ask=lambda chat_id, prompt: ask_calls.append((chat_id, prompt)) or fake_result,
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher),
            patch("sys.argv", ["codex-dispatcher", "--ask", "902", "summarize repo"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(result.exception.code, 0)
        self.assertEqual(ask_calls, [(902, "summarize repo")])
        text = output.getvalue()
        self.assertIn("Prompt completed.", text)
        self.assertIn("Chat id: 902", text)
        self.assertIn("Summary complete.", text)

    def test_main_ask_mode_rejects_blank_prompt(self) -> None:
        with patch("sys.argv", ["codex-dispatcher", "--ask", "903", "   "]):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(str(result.exception), "--ask requires a non-empty prompt.")

    def test_main_sdk_accounts_subcommand_exits_with_zero(self) -> None:
        output = io.StringIO()
        fake_dispatcher = SimpleNamespace(
            accounts=lambda: (
                SimpleNamespace(name="acc1", is_active=True),
                SimpleNamespace(name="acc2", is_active=False),
            )
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "sdk", "accounts"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Accounts", text)
        self.assertIn("- acc1 [active]", text)

    def test_main_sdk_status_subcommand_exits_with_zero(self) -> None:
        output = io.StringIO()
        fake_status = SimpleNamespace(
            active_alias="main",
            session="started",
            last_account="acc1",
            model="default",
            reasoning="default",
            sandbox="workspace-write",
            default_account="acc1",
            queue_size=0,
            worker_busy=False,
        )
        fake_dispatcher = SimpleNamespace(status=lambda chat_id: fake_status)
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "sdk", "status", "123"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Status", text)
        self.assertIn("Chat id: 123", text)
        self.assertIn("Worker busy: no", text)

    def test_main_sdk_ask_subcommand_exits_with_zero(self) -> None:
        output = io.StringIO()
        ask_calls: list[tuple[int, str]] = []
        fake_result = SimpleNamespace(success=True, final_message="Done from sdk.")
        fake_dispatcher = SimpleNamespace(
            ask=lambda chat_id, prompt: ask_calls.append((chat_id, prompt)) or fake_result,
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "sdk", "ask", "777", "summarize"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(ask_calls, [(777, "summarize")])
        self.assertIn("Prompt completed.", output.getvalue())

    def test_main_top_level_status_subcommand_exits_with_zero(self) -> None:
        output = io.StringIO()
        fake_status = SimpleNamespace(
            active_alias="main",
            session="started",
            last_account="acc1",
            model="default",
            reasoning="default",
            sandbox="workspace-write",
            default_account="acc1",
            queue_size=0,
            worker_busy=False,
        )
        fake_dispatcher = SimpleNamespace(status=lambda chat_id: fake_status)
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "status", "123"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Status", text)
        self.assertIn("Chat id: 123", text)

    def test_main_top_level_subcommand_accepts_config_option(self) -> None:
        output = io.StringIO()
        fake_health = SimpleNamespace(
            bot_status="ready",
            codex_binary="ok",
            workspace="ok",
            accounts="ok",
            default_account="acc1",
            queue_size=0,
            worker_busy=False,
            active_alias="main",
            session="not started",
        )
        fake_dispatcher = SimpleNamespace(health=lambda chat_id: fake_health)
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["codex-dispatcher", "--config", "custom.json", "health", "321"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with("custom.json")
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Health", text)
        self.assertIn("Chat id: 321", text)

    def test_main_cdx_top_level_subcommand_exits_with_zero(self) -> None:
        output = io.StringIO()
        fake_dispatcher = SimpleNamespace(
            accounts=lambda: (
                SimpleNamespace(name="acc1", is_active=True),
                SimpleNamespace(name="acc2", is_active=False),
            )
        )
        with (
            patch("codex_dispatcher.__main__.Dispatcher.from_config", return_value=fake_dispatcher) as from_config,
            patch("sys.argv", ["cdx", "accounts"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        from_config.assert_called_once_with(None)
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Accounts", text)
        self.assertIn("- acc1 [active]", text)


if __name__ == "__main__":
    unittest.main()
