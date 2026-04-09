from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.bot import CodexTelegramBot
from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig


class BotUiTests(unittest.TestCase):
    def _make_bot(self, temp_dir: Path) -> CodexTelegramBot:
        auth1 = temp_dir / "acc1.json"
        auth2 = temp_dir / "acc2.json"
        auth1.write_text("{}", encoding="utf-8")
        auth2.write_text("{}", encoding="utf-8")

        config = AppConfig(
            telegram_token="token",
            allowed_chat_ids=(),
            polling_timeout_seconds=10,
            polling_retry_delay_seconds=1,
            codex=CodexConfig(
                binary="codex",
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
        return CodexTelegramBot(config)

    def test_quick_action_mapping(self) -> None:
        self.assertEqual(CodexTelegramBot._quick_action_command("Status"), "/status")
        self.assertEqual(CodexTelegramBot._quick_action_command("Chats"), "/chats")
        self.assertEqual(CodexTelegramBot._quick_action_command("Settings"), "/settings")
        self.assertEqual(CodexTelegramBot._quick_action_command("Session ID"), "/sessionid")
        self.assertEqual(CodexTelegramBot._quick_action_command("Help"), "/help")
        self.assertEqual(CodexTelegramBot._quick_action_command("New chat"), "/newchat")
        self.assertEqual(CodexTelegramBot._quick_action_command("Full access"), "/fullaccess")
        self.assertEqual(CodexTelegramBot._quick_action_command("Ask"), "__ask_hint__")
        self.assertIsNone(CodexTelegramBot._quick_action_command("unmapped"))

    def test_confirmation_markup_contains_inline_buttons(self) -> None:
        markup = CodexTelegramBot._confirmation_markup("abc123")
        self.assertIn("inline_keyboard", markup)
        inline_keyboard = markup["inline_keyboard"]
        self.assertEqual(len(inline_keyboard), 1)
        row = inline_keyboard[0]
        self.assertEqual(row[0]["callback_data"], "cfm:abc123:yes")
        self.assertEqual(row[1]["callback_data"], "cfm:abc123:no")

    def test_main_reply_keyboard_layout(self) -> None:
        keyboard = CodexTelegramBot._main_reply_keyboard()
        self.assertIn("keyboard", keyboard)
        self.assertTrue(keyboard.get("resize_keyboard"))
        self.assertTrue(keyboard.get("is_persistent"))
        first_row = keyboard["keyboard"][0]
        self.assertEqual(first_row[0]["text"], "Ask")
        self.assertEqual(first_row[1]["text"], "Status")
        self.assertEqual(first_row[2]["text"], "Chats")
        second_row = keyboard["keyboard"][1]
        self.assertEqual(second_row[0]["text"], "Settings")
        self.assertEqual(second_row[1]["text"], "Session ID")
        self.assertEqual(second_row[2]["text"], "Help")
        third_row = keyboard["keyboard"][2]
        self.assertEqual(third_row[0]["text"], "New chat")
        self.assertEqual(third_row[1]["text"], "Full access")

    def test_attach_command_is_generated_only_for_valid_session_id(self) -> None:
        self.assertEqual(
            CodexTelegramBot._attach_command_for_session("abc-123"),
            "/attachsession abc-123",
        )
        self.assertIsNone(CodexTelegramBot._attach_command_for_session(None))
        self.assertIsNone(CodexTelegramBot._attach_command_for_session("   "))

    def test_session_summary_helper_returns_started_or_not_started(self) -> None:
        self.assertEqual(CodexTelegramBot._session_summary_text({"session_id": "s-42"}), "started")
        self.assertEqual(CodexTelegramBot._session_summary_text({"session_id": None}), "not started")

    def test_session_id_value_uses_not_started_fallback(self) -> None:
        self.assertEqual(
            CodexTelegramBot._session_id_value({"session_id": "s-42"}),
            "s-42",
        )
        self.assertEqual(
            CodexTelegramBot._session_id_value({"session_id": None}),
            "not started",
        )

    def test_command_aliases_resolve_to_canonical(self) -> None:
        self.assertEqual(CodexTelegramBot._resolve_command("/chats"), "/threads")
        self.assertEqual(CodexTelegramBot._resolve_command("/full"), "/fullaccess")
        self.assertEqual(CodexTelegramBot._resolve_command("/doc"), "/help")

    def test_command_help_text_for_alias(self) -> None:
        text = CodexTelegramBot._command_help_text("chats")
        self.assertIn("Command: /threads", text)
        self.assertIn("Usage: /threads", text)

    def test_telegram_command_hints_contain_short_names(self) -> None:
        hints = CodexTelegramBot._telegram_command_hints()
        command_names = {item["command"] for item in hints}
        self.assertIn("chats", command_names)
        self.assertIn("new", command_names)
        self.assertIn("deletecopy", command_names)

    def test_start_text_is_concise_and_not_equal_to_help(self) -> None:
        start_text = CodexTelegramBot._start_text()
        help_text = CodexTelegramBot._help_text()
        self.assertNotEqual(start_text, help_text)
        self.assertIn("Quick start:", start_text)
        self.assertIn("/help", start_text)
        self.assertIn("Plain text without a command is sent to Codex.", start_text)

    def test_help_text_is_grouped_and_low_noise(self) -> None:
        help_text = CodexTelegramBot._help_text()
        self.assertIn("Help", help_text)
        self.assertIn("Plain text without a command is sent to Codex.", help_text)
        self.assertIn("Quick start", help_text)
        self.assertIn("Chats and sessions", help_text)
        self.assertIn("Runtime and accounts", help_text)
        self.assertIn("VSCode and session files", help_text)
        self.assertIn("Utility", help_text)
        self.assertIn("/help - show command list or mini docs", help_text)
        self.assertIn("/attachsession - bind session id or rollout file to active chat", help_text)
        self.assertIn("Use /help <command> for mini docs.", help_text)
        self.assertNotIn("aliases:", help_text)

    def test_status_text_is_compact_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            bot = self._make_bot(Path(temp_dir_name))
            chat_id = 1001
            bot.state.create_or_select_thread(chat_id, "bugfix")
            bot.state.update_thread(chat_id, "bugfix", session_id="session-123", account_name="acc2")
            bot.state.set_thread_model(chat_id, "bugfix", "gpt-5.4")
            bot.state.set_thread_reasoning_effort(chat_id, "bugfix", "high")
            bot.state.set_thread_sandbox_mode(chat_id, "bugfix", "workspace-write")
            bot.state.set_active_alias(chat_id, "bugfix")
            bot.accounts.set_active_account("acc2")
            bot._jobs.put(object())
            bot._worker_busy.set()

            text = bot._status_text(chat_id)

            self.assertIn("Status", text)
            self.assertIn("Active local chat: bugfix", text)
            self.assertIn("Session: started", text)
            self.assertIn("Last account: acc2", text)
            self.assertIn("Settings", text)
            self.assertIn("Model: gpt-5.4", text)
            self.assertIn("Reasoning: high", text)
            self.assertIn("Sandbox: workspace-write", text)
            self.assertIn("Runtime", text)
            self.assertIn("Default account: acc2", text)
            self.assertIn("Queue: 1", text)
            self.assertIn("Worker busy: yes", text)
            self.assertIn("Next actions", text)
            self.assertIn("/use bugfix", text)
            self.assertIn("/sessionid", text)
            self.assertIn("/threads", text)
            self.assertNotIn("Session id: session-123", text)

    def test_status_text_uses_default_and_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            bot = self._make_bot(Path(temp_dir_name))
            chat_id = 1002
            bot.state.create_or_select_thread(chat_id, "main")
            bot.state.set_active_alias(chat_id, "main")

            text = bot._status_text(chat_id)

            self.assertIn("Session: not started", text)
            self.assertIn("Model: default", text)
            self.assertIn("Reasoning: default", text)
            self.assertIn("Sandbox: default", text)

    def test_threads_text_is_compact_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            bot = self._make_bot(Path(temp_dir_name))
            chat_id = 1003
            bot.state.update_thread(chat_id, "main", session_id="s-main", account_name="acc1")
            bot.state.create_or_select_thread(chat_id, "bugfix")
            bot.state.update_thread(chat_id, "bugfix", session_id="s-bugfix", account_name="acc2")
            bot.state.create_or_select_thread(chat_id, "docs")
            bot.state.set_active_alias(chat_id, "main")

            text = bot._threads_text(chat_id)

            self.assertIn("Local chats (3)", text)
            self.assertIn("[active] main", text)
            self.assertIn("[idle] bugfix", text)
            self.assertIn("[idle] docs", text)
            self.assertIn("Session: started", text)
            self.assertIn("Session: not started", text)
            self.assertIn("Last account: acc1", text)
            self.assertIn("Last account: acc2", text)
            self.assertIn("Last account: -", text)
            self.assertIn("/use main", text)
            self.assertIn("/use bugfix", text)
            self.assertIn("/use docs", text)
            self.assertNotIn("Quick commands:", text)
            self.assertNotIn("/attachsession", text)

    def test_usage_error_messages_are_recovery_first(self) -> None:
        self.assertEqual(
            CodexTelegramBot._usage_error("/use"),
            "Missing local chat alias.\nUse: /use <alias>\nExample: /use main\nHelp: /help use",
        )
        self.assertEqual(
            CodexTelegramBot._usage_error("/switch"),
            "Missing account name.\nUse: /switch <account>\nExample: /switch acc2\nHelp: /help switch",
        )
        self.assertEqual(
            CodexTelegramBot._usage_error("/ask"),
            "Missing prompt text.\nUse: /ask <text>\nExample: /ask explain this module\nHelp: /help ask",
        )
        self.assertEqual(
            CodexTelegramBot._usage_error("/attachsession"),
            "Missing session reference.\nUse: /attachsession <session_id_or_path>\nExample: /attachsession 019d....\nHelp: /help attachsession",
        )

    def test_unknown_command_text_is_short_and_actionable(self) -> None:
        self.assertEqual(
            CodexTelegramBot._unknown_command_text(),
            "Unknown command.\nUse /help for the command list.",
        )

    def test_unknown_reference_messages_are_actionable(self) -> None:
        self.assertEqual(
            CodexTelegramBot._unknown_reference_text("/use", KeyError("draft")),
            "Local chat not found: draft.\nUse /threads to see available chats.",
        )
        self.assertEqual(
            CodexTelegramBot._unknown_reference_text("/switch", KeyError("acc-x")),
            "Account not found: acc-x.\nUse /accounts to see available accounts.",
        )

    def test_attach_file_not_found_message_has_recovery_steps(self) -> None:
        message = CodexTelegramBot._file_not_found_text("/attachsession", FileNotFoundError("missing"))
        self.assertIn("Session source not found.", message)
        self.assertIn("Use: /attachsession <session_id_or_path>", message)
        self.assertIn("Help: /help attachsession", message)

    def test_invalid_mode_messages_include_recovery_hint(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Invalid reasoning level: turbo\\.\nUse: /reasoning <low\\|medium\\|high\\|xhigh\\|default>\nExample: /reasoning high\nHelp: /help reasoning",
        ):
            CodexTelegramBot._parse_reasoning_effort("turbo")

        with self.assertRaisesRegex(
            ValueError,
            "Invalid sandbox mode: unsafe-fast\\.\nUse: /sandbox <read-only\\|workspace-write\\|danger-full-access\\|default>\nExample: /sandbox workspace-write\nHelp: /help sandbox",
        ):
            CodexTelegramBot._parse_sandbox_mode("unsafe-fast")

        with self.assertRaisesRegex(
            ValueError,
            "Invalid edit mode: fast\\.\nUse: /edit on\\|off\\|full\\|default\nExample: /edit on\nHelp: /help edit",
        ):
            CodexTelegramBot._parse_edit_mode("fast")


if __name__ == "__main__":
    unittest.main()
