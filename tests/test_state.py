from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_create_alias_and_persist_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            state_path = Path(temp_dir_name) / "bot_state.json"
            store = StateStore(state_path)

            store.create_or_select_thread(1001, "feature-a")
            store.update_thread(1001, "feature-a", session_id="thread-001", account_name="acc2")

            reopened = StateStore(state_path)
            active_alias, thread = reopened.get_active_thread(1001)

            self.assertEqual(active_alias, "feature-a")
            self.assertEqual(thread["session_id"], "thread-001")
            self.assertEqual(thread["last_account"], "acc2")

    def test_reset_thread_clears_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            state_path = Path(temp_dir_name) / "bot_state.json"
            store = StateStore(state_path)

            store.update_thread(1001, "main", session_id="thread-001", account_name="acc1")
            store.reset_thread(1001, "main")
            _, thread = store.get_active_thread(1001)

            self.assertIsNone(thread["session_id"])
            self.assertIsNone(thread["last_account"])

    def test_get_thread_returns_requested_alias_even_if_it_is_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            state_path = Path(temp_dir_name) / "bot_state.json"
            store = StateStore(state_path)

            store.create_or_select_thread(1001, "alpha")
            store.update_thread(1001, "alpha", session_id="thread-alpha", account_name="acc1")
            store.create_or_select_thread(1001, "beta")
            store.update_thread(1001, "beta", session_id="thread-beta", account_name="acc2")
            store.set_active_alias(1001, "beta")

            thread = store.get_thread(1001, "alpha")

            self.assertEqual(thread["session_id"], "thread-alpha")
            self.assertEqual(thread["last_account"], "acc1")

    def test_codex_settings_persist_and_survive_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            state_path = Path(temp_dir_name) / "bot_state.json"
            store = StateStore(state_path)

            store.create_or_select_thread(1001, "feature-a")
            store.set_thread_model(1001, "feature-a", "o3")
            store.set_thread_reasoning_effort(1001, "feature-a", "high")
            store.set_thread_sandbox_mode(1001, "feature-a", "workspace-write")
            store.update_thread(1001, "feature-a", session_id="thread-001", account_name="acc2")
            store.reset_thread(1001, "feature-a")

            reopened = StateStore(state_path)
            active_alias, thread = reopened.get_active_thread(1001)

            self.assertEqual(active_alias, "feature-a")
            self.assertIsNone(thread["session_id"])
            self.assertEqual(thread["model"], "o3")
            self.assertEqual(thread["reasoning_effort"], "high")
            self.assertEqual(thread["sandbox_mode"], "workspace-write")
            self.assertIsNone(thread["last_account"])


if __name__ == "__main__":
    unittest.main()
