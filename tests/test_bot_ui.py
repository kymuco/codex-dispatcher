from __future__ import annotations

import unittest

from codex_dispatcher.bot import CodexTelegramBot


class BotUiTests(unittest.TestCase):
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
        self.assertIn("Plain text without a command is also sent to Codex.", start_text)

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
