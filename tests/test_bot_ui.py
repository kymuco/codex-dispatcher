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


if __name__ == "__main__":
    unittest.main()
