from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig
from codex_dispatcher.core import DispatcherService, StartupCheckError


class DispatcherServiceTests(unittest.TestCase):
    def _make_config(
        self,
        temp_dir: Path,
        *,
        binary: str | None = None,
        cwd: Path | None = None,
        token: str = "123456:abc",
    ) -> AppConfig:
        auth1 = temp_dir / "acc1.json"
        auth2 = temp_dir / "acc2.json"
        auth1.write_text("{}", encoding="utf-8")
        auth2.write_text("{}", encoding="utf-8")

        return AppConfig(
            telegram_token=token,
            allowed_chat_ids=(),
            polling_timeout_seconds=10,
            polling_retry_delay_seconds=1,
            codex=CodexConfig(
                binary=binary or sys.executable,
                cwd=cwd or temp_dir,
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

    def test_run_startup_checks_initializes_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            config = self._make_config(Path(temp_dir_name))
            service = DispatcherService(config)

            self.assertIsNone(service.codex)
            service.run_startup_checks()
            self.assertIsNotNone(service.codex)
            self.assertTrue(service.startup_report()["ready"])

    def test_run_startup_checks_raises_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            config = self._make_config(
                Path(temp_dir_name),
                binary="missing-codex-binary",
            )
            service = DispatcherService(config)

            with self.assertRaises(StartupCheckError) as context:
                service.run_startup_checks()

            text = str(context.exception)
            self.assertIn("Startup check failed:", text)
            self.assertIn("Codex binary was not found:", text)

    def test_status_health_and_threads_snapshots_reflect_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            runtime = {"queue_size": 1, "worker_busy": True}
            config = self._make_config(Path(temp_dir_name))
            service = DispatcherService(
                config,
                queue_size_getter=lambda: runtime["queue_size"],
                worker_busy_getter=lambda: runtime["worker_busy"],
            )
            chat_id = 5001

            service.create_or_select_chat(chat_id, "bugfix")
            service.set_model(chat_id, "bugfix", "gpt-5.4")
            service.set_reasoning(chat_id, "bugfix", "high")
            service.set_sandbox(chat_id, "bugfix", "workspace-write")
            service.state.update_thread(chat_id, "bugfix", session_id="session-123", account_name="acc2")
            service.switch_account("acc2")

            service.create_or_select_chat(chat_id, "docs")
            service.use_chat(chat_id, "bugfix")

            status = service.get_status(chat_id)
            self.assertEqual(status.active_alias, "bugfix")
            self.assertEqual(status.session, "started")
            self.assertEqual(status.last_account, "acc2")
            self.assertEqual(status.model, "gpt-5.4")
            self.assertEqual(status.reasoning, "high")
            self.assertEqual(status.sandbox, "workspace-write")
            self.assertEqual(status.default_account, "acc2")
            self.assertEqual(status.queue_size, 1)
            self.assertTrue(status.worker_busy)

            health = service.get_health(chat_id)
            self.assertEqual(health.bot_status, "ready")
            self.assertEqual(health.codex_binary, "ok")
            self.assertEqual(health.workspace, "ok")
            self.assertEqual(health.accounts, "ok")
            self.assertEqual(health.active_alias, "bugfix")
            self.assertEqual(health.session, "started")
            self.assertEqual(health.queue_size, 1)
            self.assertTrue(health.worker_busy)

            threads = service.list_threads(chat_id)
            aliases = [item.alias for item in threads.items]
            self.assertEqual(aliases[0], "bugfix")
            self.assertIn("docs", aliases)

    def test_build_prompt_job_and_reset_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            config = self._make_config(Path(temp_dir_name))
            service = DispatcherService(config)
            chat_id = 5002
            service.create_or_select_chat(chat_id, "main")

            job = service.build_prompt_job(
                chat_id=chat_id,
                prompt="inspect tests",
                reply_to_message_id=77,
            )
            self.assertEqual(job.alias, "main")
            self.assertEqual(job.prompt, "inspect tests")
            self.assertEqual(job.reply_to_message_id, 77)

            service.state.update_thread(chat_id, "main", session_id="session-main")
            service.reset_chat(chat_id, "main")
            snapshot = service.get_session_id(chat_id)
            self.assertIsNone(snapshot.session_id)


if __name__ == "__main__":
    unittest.main()
