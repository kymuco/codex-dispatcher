from __future__ import annotations

import unittest

from codex_dispatcher.bot import CodexTelegramBot


class BotUiTests(unittest.TestCase):
    def test_quick_action_mapping(self) -> None:
        self.assertEqual(CodexTelegramBot._quick_action_command("Status"), "/status")
        self.assertEqual(CodexTelegramBot._quick_action_command("threads"), "/threads")
        self.assertEqual(CodexTelegramBot._quick_action_command("Settings"), "/settings")
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
        self.assertEqual(first_row[2]["text"], "Threads")


if __name__ == "__main__":
    unittest.main()
