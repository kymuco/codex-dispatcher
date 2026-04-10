from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.config import AccountConfig, AppConfig, CodexConfig
from codex_dispatcher.session_manager import SessionManager
from codex_dispatcher.state import StateStore


class SessionManagerTests(unittest.TestCase):
    def _make_config(self, temp_dir: Path, *, cwd: Path | None = None) -> AppConfig:
        auth_file = temp_dir / "auth.json"
        auth_file.write_text("{}", encoding="utf-8")
        return AppConfig(
            telegram_token="token",
            allowed_chat_ids=(),
            polling_timeout_seconds=10,
            polling_retry_delay_seconds=1,
            codex=CodexConfig(
                binary="codex",
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

    def _fetch_thread_row(self, database_path: Path, session_id: str) -> tuple | None:
        connection = sqlite3.connect(database_path)
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT id, rollout_path, source, title FROM threads WHERE id = ?",
                (session_id,),
            )
            return cursor.fetchone()
        finally:
            connection.close()

    def _seed_minimal_threads_row(self, database_path: Path, *, session_id: str, rollout_path: str) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path)
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    rollout_path TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                "INSERT OR REPLACE INTO threads (id, rollout_path) VALUES (?, ?)",
                (session_id, rollout_path),
            )
            connection.commit()
        finally:
            connection.close()

    def test_attach_from_file_imports_session_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)

            source_file = temp_dir / "external" / "sessions" / "2026" / "04" / "09" / "rollout-test.jsonl"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-123"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            attachment = manager.attach_to_alias(chat_id=1, alias="main", session_ref=str(source_file))

            self.assertEqual(attachment.source_session_id, "session-123")
            self.assertNotEqual(attachment.session_id, "session-123")
            self.assertTrue(attachment.imported)
            self.assertTrue(attachment.rekeyed)
            self.assertTrue(attachment.target_file.exists())
            self.assertIn(attachment.session_id, attachment.target_file.name)
            self.assertNotIn("session-123", attachment.target_file.name)
            first_line = attachment.target_file.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn(f'"id":"{attachment.session_id}"', first_line)
            _, thread = state.get_active_thread(1)
            self.assertEqual(thread["session_id"], attachment.session_id)

    def test_attach_session_ref_resolves_relative_to_codex_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            workspace_dir = temp_dir / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            config = self._make_config(temp_dir, cwd=workspace_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)

            relative_ref = Path("imports") / "rollout-relative.jsonl"
            source_file = workspace_dir / relative_ref
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-rel"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            attachment = manager.attach_to_alias(chat_id=1, alias="main", session_ref=str(relative_ref))

            self.assertEqual(attachment.source_session_id, "session-rel")
            self.assertTrue(attachment.imported)
            self.assertTrue(attachment.target_file.exists())
            _, thread = state.get_active_thread(1)
            self.assertEqual(thread["session_id"], attachment.session_id)

    def test_attach_by_session_id_finds_session_in_home_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)

            source_home = temp_dir / "source-home"
            source_sessions = source_home / "sessions" / "2026" / "04" / "09"
            source_sessions.mkdir(parents=True, exist_ok=True)
            session_file = source_sessions / "rollout-session-456.jsonl"
            session_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-456"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (source_home / "session_index.jsonl").write_text(
                json.dumps(
                    {
                        "id": "session-456",
                        "thread_name": "Imported Session",
                        "updated_at": "2026-04-09T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manager.source_homes = [config.codex.state_dir, source_home]

            attachment = manager.attach_to_alias(chat_id=1, alias="main", session_ref="session-456")

            self.assertEqual(attachment.source_session_id, "session-456")
            self.assertNotEqual(attachment.session_id, "session-456")
            self.assertTrue(attachment.target_file.exists())
            index_contents = (config.codex.state_dir / "session_index.jsonl").read_text(encoding="utf-8")
            self.assertIn(attachment.session_id, index_contents)
            _, thread = state.get_active_thread(1)
            self.assertEqual(thread["session_id"], attachment.session_id)

    def test_attach_by_session_id_can_resolve_from_threads_rollout_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)

            source_home = temp_dir / "source-home"
            source_rollout = source_home / "sessions" / "2026" / "04" / "09" / "rollout-random-name.jsonl"
            source_rollout.parent.mkdir(parents=True, exist_ok=True)
            source_rollout.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-db-path"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self._seed_minimal_threads_row(
                source_home / "state_5.sqlite",
                session_id="session-db-path",
                rollout_path=manager._normalize_rollout_path(source_rollout),
            )
            manager.source_homes = [config.codex.state_dir, source_home]

            attachment = manager.attach_to_alias(chat_id=1, alias="main", session_ref="session-db-path")

            self.assertEqual(attachment.source_session_id, "session-db-path")
            self.assertTrue(attachment.imported)
            self.assertTrue(attachment.rekeyed)
            self.assertTrue(attachment.target_file.exists())

    def test_attach_prefers_external_source_over_conflicting_local_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)

            local_file = config.codex.state_dir / "sessions" / "2026" / "04" / "09" / "rollout-session-shared.jsonl"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-shared"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            source_home = temp_dir / "source-home"
            source_sessions = source_home / "sessions" / "2026" / "04" / "09"
            source_sessions.mkdir(parents=True, exist_ok=True)
            source_file = source_sessions / "rollout-session-shared.jsonl"
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-shared"},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-04-09T00:01:00Z",
                        "type": "event_msg",
                        "payload": {"type": "agent_message", "message": "from-external"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (source_home / "session_index.jsonl").write_text(
                json.dumps(
                    {
                        "id": "session-shared",
                        "thread_name": "External Session",
                        "updated_at": "2026-04-09T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manager.source_homes = [config.codex.state_dir, source_home]

            attachment = manager.attach_to_alias(chat_id=1, alias="main", session_ref="session-shared")

            target_contents = attachment.target_file.read_text(encoding="utf-8")
            self.assertIn("from-external", target_contents)
            self.assertNotEqual(attachment.target_file.resolve(), local_file.resolve())

    def test_export_to_vscode_creates_one_copy_in_dedicated_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)
            manager.vscode_home = temp_dir / "vscode-home"
            manager.source_homes = [config.codex.state_dir, manager.vscode_home]

            source_file = config.codex.state_dir / "sessions" / "2026" / "04" / "09" / "rollout-session-789.jsonl"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-789"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state.update_thread(1, "main", session_id="session-789", account_name="acc1")

            export = manager.export_alias_to_vscode(chat_id=1, alias="main")

            self.assertEqual(export.action, "created")
            self.assertTrue(export.target_file.exists())
            self.assertIn("telegram-bot", str(export.target_file))

            export_again = manager.export_alias_to_vscode(chat_id=1, alias="main")
            self.assertEqual(export_again.action, "exists")
            self.assertEqual(export_again.target_file, export.target_file)

    def test_export_to_vscode_does_not_overwrite_existing_vscode_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)
            manager.vscode_home = temp_dir / "vscode-home"
            manager.source_homes = [config.codex.state_dir, manager.vscode_home]

            source_file = config.codex.state_dir / "sessions" / "2026" / "04" / "09" / "rollout-session-999.jsonl"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-999"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            existing_file = manager.vscode_home / "sessions" / "2026" / "04" / "09" / "rollout-session-999.jsonl"
            existing_file.parent.mkdir(parents=True, exist_ok=True)
            existing_file.write_text("old-data\n", encoding="utf-8")
            (manager.vscode_home / "session_index.jsonl").write_text(
                json.dumps(
                    {
                        "id": "session-999",
                        "thread_name": "Existing Session",
                        "updated_at": "2026-04-09T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state.update_thread(1, "main", session_id="session-999", account_name="acc1")

            export = manager.export_alias_to_vscode(chat_id=1, alias="main")

            self.assertEqual(export.action, "exists")
            self.assertEqual(export.target_file, existing_file)
            self.assertEqual(existing_file.read_text(encoding="utf-8"), "old-data\n")

    def test_sync_to_vscode_overwrites_existing_vscode_session_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)
            manager.vscode_home = temp_dir / "vscode-home"
            manager.source_homes = [config.codex.state_dir, manager.vscode_home]

            source_file = config.codex.state_dir / "sessions" / "2026" / "04" / "09" / "rollout-session-1000.jsonl"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-1000"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            existing_file = manager.vscode_home / "sessions" / "2026" / "04" / "09" / "rollout-session-1000.jsonl"
            existing_file.parent.mkdir(parents=True, exist_ok=True)
            existing_file.write_text("old-data\n", encoding="utf-8")
            (manager.vscode_home / "session_index.jsonl").write_text(
                json.dumps(
                    {
                        "id": "session-1000",
                        "thread_name": "Existing Session",
                        "updated_at": "2026-04-09T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state.update_thread(1, "main", session_id="session-1000", account_name="acc1")

            export = manager.sync_alias_to_vscode(chat_id=1, alias="main")

            self.assertEqual(export.action, "updated")
            self.assertEqual(export.target_file, existing_file)
            self.assertIn('"payload": {"id": "session-1000"}', existing_file.read_text(encoding="utf-8"))

    def test_clone_to_vscode_creates_independent_view_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)
            manager.vscode_home = temp_dir / "vscode-home"
            manager.source_homes = [config.codex.state_dir, manager.vscode_home]

            source_file = config.codex.state_dir / "sessions" / "2026" / "04" / "09" / "rollout-session-2000.jsonl"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-2000"},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-04-09T00:01:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "hello user"}],
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-04-09T00:02:00Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "last_agent_message": "this should be preserved",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-04-09T00:03:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "hello assistant"}],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state.update_thread(1, "main", session_id="session-2000", account_name="acc1")

            clone = manager.clone_alias_to_vscode(chat_id=1, alias="main", title="Temp inspect")

            self.assertNotEqual(clone.cloned_session_id, "session-2000")
            self.assertTrue(clone.target_file.exists())
            self.assertIn(clone.cloned_session_id, clone.target_file.name)
            thread_row = self._fetch_thread_row(manager.vscode_home / "state_5.sqlite", clone.cloned_session_id)
            self.assertIsNotNone(thread_row)
            assert thread_row is not None
            self.assertEqual(thread_row[0], clone.cloned_session_id)
            self.assertEqual(thread_row[1], manager._normalize_rollout_path(clone.target_file))
            self.assertEqual(thread_row[2], "vscode")
            self.assertEqual(thread_row[3], "TEMP VIEW - Temp inspect")
            cloned_lines = clone.target_file.read_text(encoding="utf-8").splitlines()
            first_line = cloned_lines[0]
            self.assertIn(f'"id":"{clone.cloned_session_id}"', first_line)
            self.assertEqual(len(cloned_lines), 4)
            self.assertIn('"role": "user"', cloned_lines[1])
            self.assertIn('"type": "event_msg"', cloned_lines[2])
            self.assertIn("task_complete", cloned_lines[2])
            self.assertIn('"role": "assistant"', cloned_lines[3])
            registry_contents = (temp_dir / "data" / "vscode_view_copies.json").read_text(encoding="utf-8")
            self.assertIn(clone.cloned_session_id, registry_contents)

    def test_delete_vscode_view_copy_only_deletes_view_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)
            manager.vscode_home = temp_dir / "vscode-home"
            manager.source_homes = [config.codex.state_dir, manager.vscode_home]

            source_file = config.codex.state_dir / "sessions" / "2026" / "04" / "09" / "rollout-session-3000.jsonl"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "session-3000"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state.update_thread(1, "main", session_id="session-3000", account_name="acc1")
            clone = manager.clone_alias_to_vscode(chat_id=1, alias="main", title="Disposable view")

            deleted = manager.delete_vscode_view_copy(clone.cloned_session_id)

            self.assertEqual(deleted, clone.target_file.resolve())
            self.assertFalse(clone.target_file.exists())
            self.assertTrue(source_file.exists())
            thread_row = self._fetch_thread_row(manager.vscode_home / "state_5.sqlite", clone.cloned_session_id)
            self.assertIsNone(thread_row)
            index_path = manager.vscode_home / "session_index.jsonl"
            if index_path.exists():
                index_contents = index_path.read_text(encoding="utf-8")
                self.assertNotIn(clone.cloned_session_id, index_contents)
            registry_contents = (temp_dir / "data" / "vscode_view_copies.json").read_text(encoding="utf-8")
            self.assertNotIn(clone.cloned_session_id, registry_contents)

    def test_repair_colliding_local_sessions_rekeys_existing_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config = self._make_config(temp_dir)
            state = StateStore(temp_dir / "bot_state.json")
            manager = SessionManager(config, state)
            manager.vscode_home = temp_dir / "vscode-home"
            manager.source_homes = [config.codex.state_dir, manager.vscode_home]

            shared_session_id = "session-collision"
            vscode_file = manager.vscode_home / "sessions" / "2026" / "04" / "09" / "rollout-session-collision.jsonl"
            vscode_file.parent.mkdir(parents=True, exist_ok=True)
            vscode_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-09T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": shared_session_id},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            bot_file = config.codex.state_dir / "sessions" / "2026" / "04" / "09" / "rollout-session-collision.jsonl"
            bot_file.parent.mkdir(parents=True, exist_ok=True)
            bot_file.write_text(vscode_file.read_text(encoding="utf-8"), encoding="utf-8")
            state.update_thread(1, "main", session_id=shared_session_id, account_name="acc1")

            repairs = manager.repair_colliding_local_sessions()

            self.assertEqual(len(repairs), 1)
            repair = repairs[0]
            self.assertEqual(repair.source_session_id, shared_session_id)
            self.assertNotEqual(repair.repaired_session_id, shared_session_id)
            self.assertTrue(repair.target_file.exists())
            _, thread = state.get_active_thread(1)
            self.assertEqual(thread["session_id"], repair.repaired_session_id)
            first_line = repair.target_file.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn(f'"id":"{repair.repaired_session_id}"', first_line)
            backup_names = {path.name for path in (temp_dir / "backups").iterdir()}
            self.assertTrue(any(name.startswith("bot_state.json.") for name in backup_names))


if __name__ == "__main__":
    unittest.main()
