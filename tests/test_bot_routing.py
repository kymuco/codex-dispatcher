from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from codex_dispatcher.bot import CodexTelegramBot, StartupCheckError
from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.callback_answers: list[dict[str, Any]] = []

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                "reply_markup": reply_markup,
            }
        )

    def answer_callback_query(self, **payload: Any) -> None:
        self.callback_answers.append(payload)
        return

    def clear_inline_keyboard(self, **_: Any) -> None:
        return


class BotRoutingTests(unittest.TestCase):
    def _make_bot(
        self,
        temp_dir: Path,
        *,
        binary: str | None = None,
        cwd: Path | None = None,
    ) -> CodexTelegramBot:
        auth_file = temp_dir / "auth.json"
        auth_file.write_text("{}", encoding="utf-8")
        config = AppConfig(
            telegram_token="123456:abc",
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
            accounts=(AccountConfig(name="acc1", auth_file=auth_file),),
            config_path=temp_dir / "config.json",
        )
        bot = CodexTelegramBot(config)
        bot.telegram = _FakeTelegramClient()
        return bot

    def test_command_routing_start_help_health_and_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            bot = self._make_bot(Path(temp_dir_name))
            chat_id = 9001

            bot._handle_command(chat_id, None, "/start")
            self.assertIn("Quick start:", bot.telegram.messages[-1]["text"])
            self.assertNotIn("Quick start\n/help -", bot.telegram.messages[-1]["text"])

            bot._handle_command(chat_id, None, "/help")
            self.assertIn("Help", bot.telegram.messages[-1]["text"])
            self.assertIn("Quick start", bot.telegram.messages[-1]["text"])

            bot._handle_command(chat_id, None, "/health")
            self.assertIn("Health", bot.telegram.messages[-1]["text"])
            self.assertIn("Bot: ready", bot.telegram.messages[-1]["text"])
            self.assertIn("Runtime", bot.telegram.messages[-1]["text"])

            bot._handle_command(chat_id, None, "/nope")
            self.assertEqual(
                bot.telegram.messages[-1]["text"],
                "Unknown command.\nUse /help for the command list.",
            )

    def test_plain_text_update_routes_to_enqueue_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            bot = self._make_bot(Path(temp_dir_name))
            update = {
                "update_id": 1,
                "message": {
                    "message_id": 10,
                    "chat": {"id": 9010},
                    "text": "hello from telegram",
                },
            }

            bot._handle_update(update)

            self.assertEqual(bot._jobs.qsize(), 1)
            self.assertIn(
                "Prompt queued for local chat 'main'.",
                bot.telegram.messages[-1]["text"],
            )

    def test_callback_routing_status_health_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            bot = self._make_bot(Path(temp_dir_name))
            callback_query = {
                "id": "cb-1",
                "data": "act:status:health",
                "message": {
                    "message_id": 55,
                    "chat": {"id": 9020},
                },
            }

            bot._handle_callback_query(callback_query)

            self.assertIn("Health", bot.telegram.messages[-1]["text"])
            self.assertTrue(bot.telegram.callback_answers)
            self.assertEqual(bot.telegram.callback_answers[-1]["text"], "Action completed.")

    def test_callback_routing_threads_use_alias_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            bot = self._make_bot(Path(temp_dir_name))
            chat_id = 9030
            bot.state.create_or_select_thread(chat_id, "main")
            bot.state.create_or_select_thread(chat_id, "bugfix")
            bot.state.set_active_alias(chat_id, "main")
            callback_query = {
                "id": "cb-2",
                "data": "act:threads:use:bugfix",
                "message": {
                    "message_id": 56,
                    "chat": {"id": chat_id},
                },
            }

            bot._handle_callback_query(callback_query)

            active_alias, _ = bot.state.get_active_thread(chat_id)
            self.assertEqual(active_alias, "bugfix")
            self.assertEqual(bot.telegram.messages[-1]["text"], "Switched to local chat: bugfix")
            self.assertEqual(bot.telegram.callback_answers[-1]["text"], "Action completed.")

    def test_startup_checks_fail_early_with_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            missing_cwd = temp_dir / "missing-workspace"
            bot = self._make_bot(temp_dir, binary="missing-codex-binary", cwd=missing_cwd)

            with self.assertRaises(StartupCheckError) as context:
                bot._run_startup_checks()

            text = str(context.exception)
            self.assertIn("Startup check failed:", text)
            self.assertTrue(
                "Codex binary was not found:" in text or "Workspace directory is missing:" in text
            )


if __name__ == "__main__":
    unittest.main()
