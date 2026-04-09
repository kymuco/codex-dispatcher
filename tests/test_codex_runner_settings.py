from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.accounts import AccountManager
from codex_dispatcher.codex_runner import CodexService
from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig
from codex_dispatcher.state import StateStore


class CodexRunnerSettingsTests(unittest.TestCase):
    def test_build_exec_command_uses_full_auto_for_resumed_workspace_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            binary = temp_dir / "codex.exe"
            binary.write_text("", encoding="utf-8")
            auth_file = temp_dir / "auth.json"
            auth_file.write_text("{}", encoding="utf-8")

            config = AppConfig(
                telegram_token="token",
                allowed_chat_ids=(),
                polling_timeout_seconds=10,
                polling_retry_delay_seconds=1,
                codex=CodexConfig(
                    binary=str(binary),
                    cwd=temp_dir,
                    state_dir=temp_dir / "state",
                    model="gpt-5.4-mini",
                    extra_args=("--skip-git-repo-check",),
                    cli_auth_credentials_store="file",
                    auto_switch_on_limit=True,
                    response_timeout_seconds=10,
                    limit_markers=("usage limit",),
                ),
                accounts=(AccountConfig(name="acc1", auth_file=auth_file),),
                config_path=temp_dir / "config.json",
            )
            state = StateStore(temp_dir / "bot_state.json")
            accounts = AccountManager(config, state)
            service = CodexService(config, state, accounts)

            self.assertEqual(service._resolve_model({"model": "o3"}), "o3")
            self.assertEqual(service._resolve_model({"model": None}), "gpt-5.4-mini")
            self.assertIsNone(service._resolve_reasoning_effort({"reasoning_effort": None}))
            self.assertEqual(service._resolve_sandbox_mode({"sandbox_mode": "read-only"}), "read-only")

            command = service._build_exec_command(
                prompt="Fix the bug",
                output_path=temp_dir / "final.txt",
                session_id="thread-1",
                model="o3",
                reasoning_effort="high",
                sandbox_mode="workspace-write",
            )

            self.assertEqual(command[0], str(binary))
            self.assertEqual(command[1], "--config")
            self.assertEqual(command[2], 'cli_auth_credentials_store="file"')
            self.assertIn("exec", command)
            self.assertIn("resume", command)
            self.assertIn("--full-auto", command)
            self.assertIn("--model", command)
            self.assertIn("o3", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertIn('model_reasoning_effort="high"', command)
            self.assertNotIn("--sandbox", command)
            self.assertLess(command.index("resume"), command.index("--full-auto"))
            self.assertLess(command.index("--full-auto"), command.index("--json"))
            self.assertEqual(command[-2:], ["thread-1", "Fix the bug"])

    def test_build_exec_command_uses_sandbox_for_fresh_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            binary = temp_dir / "codex.exe"
            binary.write_text("", encoding="utf-8")
            auth_file = temp_dir / "auth.json"
            auth_file.write_text("{}", encoding="utf-8")

            config = AppConfig(
                telegram_token="token",
                allowed_chat_ids=(),
                polling_timeout_seconds=10,
                polling_retry_delay_seconds=1,
                codex=CodexConfig(
                    binary=str(binary),
                    cwd=temp_dir,
                    state_dir=temp_dir / "state",
                    model="gpt-5.4-mini",
                    extra_args=("--skip-git-repo-check",),
                    cli_auth_credentials_store="file",
                    auto_switch_on_limit=True,
                    response_timeout_seconds=10,
                    limit_markers=("usage limit",),
                ),
                accounts=(AccountConfig(name="acc1", auth_file=auth_file),),
                config_path=temp_dir / "config.json",
            )
            state = StateStore(temp_dir / "bot_state.json")
            accounts = AccountManager(config, state)
            service = CodexService(config, state, accounts)

            command = service._build_exec_command(
                prompt="Fix the bug",
                output_path=temp_dir / "final.txt",
                session_id=None,
                model="o3",
                reasoning_effort="high",
                sandbox_mode="workspace-write",
            )

            self.assertIn("--sandbox", command)
            self.assertIn("workspace-write", command)
            self.assertNotIn("--full-auto", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)


if __name__ == "__main__":
    unittest.main()
