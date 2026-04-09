from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_dispatcher.purge_codex_session import CodexSessionPurger


class CodexSessionPurgerTests(unittest.TestCase):
    def _create_database(self, database_path: Path) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.executescript(
                """
                CREATE TABLE threads (
                    id TEXT PRIMARY KEY,
                    rollout_path TEXT NOT NULL
                );
                CREATE TABLE stage1_outputs (
                    thread_id TEXT PRIMARY KEY
                );
                CREATE TABLE thread_dynamic_tools (
                    thread_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (thread_id, position)
                );
                CREATE TABLE thread_spawn_edges (
                    parent_thread_id TEXT NOT NULL,
                    child_thread_id TEXT NOT NULL PRIMARY KEY
                );
                CREATE TABLE agent_job_items (
                    job_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    assigned_thread_id TEXT,
                    PRIMARY KEY (job_id, item_id)
                );
                """
            )
        finally:
            connection.close()

    def _insert_session_rows(self, database_path: Path, session_id: str, rollout_path: Path) -> None:
        connection = sqlite3.connect(database_path)
        try:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO threads (id, rollout_path) VALUES (?, ?)",
                (session_id, str(rollout_path)),
            )
            cursor.execute(
                "INSERT INTO stage1_outputs (thread_id) VALUES (?)",
                (session_id,),
            )
            cursor.execute(
                "INSERT INTO thread_dynamic_tools (thread_id, position) VALUES (?, ?)",
                (session_id, 1),
            )
            cursor.execute(
                "INSERT INTO thread_spawn_edges (parent_thread_id, child_thread_id) VALUES (?, ?)",
                (session_id, f"{session_id}-child"),
            )
            cursor.execute(
                "INSERT INTO agent_job_items (job_id, item_id, assigned_thread_id) VALUES (?, ?, ?)",
                (f"job-{session_id}", "item-1", session_id),
            )
            connection.commit()
        finally:
            connection.close()

    def _read_jsonl_ids(self, path: Path) -> list[str | None]:
        ids: list[str | None] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                ids.append(None)
                continue
            ids.append(payload.get("id") if isinstance(payload, dict) else None)
        return ids

    def test_purge_session_removes_database_index_and_rollout_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            home = temp_dir / ".codex"
            sessions_root = home / "sessions" / "2026" / "04" / "09"
            sessions_root.mkdir(parents=True, exist_ok=True)
            backups_root = temp_dir / "backups"

            database_path = home / "state_5.sqlite"
            self._create_database(database_path)

            target_session_id = "019d71cc-5573-76f0-8dbc-1bc2023d8c44"
            broken_session_id = "019d70d7-d427-7ba1-a6f5-5ddd6e382746"

            target_rollout = sessions_root / f"rollout-2026-04-09T16-31-49-{target_session_id}.jsonl"
            broken_rollout = sessions_root / f"rollout-2026-04-09T12-04-46-{broken_session_id}.jsonl"
            target_rollout.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": target_session_id,
                                },
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        json.dumps({"type": "event_msg", "payload": {"type": "message"}}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            broken_rollout.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": broken_session_id,
                                },
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        json.dumps({"type": "event_msg", "payload": {"type": "message"}}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self._insert_session_rows(database_path, target_session_id, target_rollout)
            self._insert_session_rows(database_path, broken_session_id, broken_rollout)

            index_path = home / "session_index.jsonl"
            index_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "id": target_session_id,
                                "thread_name": "Target session",
                                "updated_at": "2026-04-09T10:33:37.1171803Z",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "id": "other-session",
                                "thread_name": "Keep me",
                                "updated_at": "2026-04-09T10:33:37.1171803Z",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            purger = CodexSessionPurger(home, backups_root=backups_root)
            reports = purger.purge([target_session_id, broken_session_id])
            self.assertEqual([report.session_id for report in reports], [target_session_id, broken_session_id])

            target_report = reports[0]
            broken_report = reports[1]

            self.assertTrue(target_report.applied)
            self.assertTrue(target_report.thread_row_deleted)
            self.assertEqual(target_report.index_entries_removed, 1)
            self.assertTrue(target_report.rollout_file_deleted)
            self.assertEqual(target_report.stage1_outputs_deleted, 1)
            self.assertEqual(target_report.thread_dynamic_tools_deleted, 1)
            self.assertEqual(target_report.thread_spawn_edges_deleted, 1)
            self.assertEqual(target_report.assigned_thread_refs_cleared, 1)

            self.assertTrue(broken_report.applied)
            self.assertTrue(broken_report.thread_row_deleted)
            self.assertEqual(broken_report.index_entries_removed, 0)
            self.assertTrue(broken_report.rollout_file_deleted)

            connection = sqlite3.connect(database_path)
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT COUNT(*) FROM threads WHERE id = ?", (target_session_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute("SELECT COUNT(*) FROM threads WHERE id = ?", (broken_session_id,))
                self.assertEqual(cursor.fetchone()[0], 0)

                cursor.execute("SELECT COUNT(*) FROM stage1_outputs WHERE thread_id = ?", (target_session_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute("SELECT COUNT(*) FROM thread_dynamic_tools WHERE thread_id = ?", (target_session_id,))
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT COUNT(*) FROM thread_spawn_edges WHERE parent_thread_id = ? OR child_thread_id = ?",
                    (target_session_id, target_session_id),
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT assigned_thread_id FROM agent_job_items WHERE job_id = ?",
                    (f"job-{target_session_id}",),
                )
                row = cursor.fetchone()
                self.assertIsNotNone(row)
                self.assertIsNone(row[0])

                cursor.execute(
                    "SELECT assigned_thread_id FROM agent_job_items WHERE job_id = ?",
                    (f"job-{broken_session_id}",),
                )
                row = cursor.fetchone()
                self.assertIsNotNone(row)
                self.assertIsNone(row[0])
            finally:
                connection.close()

            self.assertFalse(target_rollout.exists())
            self.assertFalse(broken_rollout.exists())

            self.assertTrue(index_path.exists())
            self.assertEqual(self._read_jsonl_ids(index_path), ["other-session"])

            self.assertTrue(any(path.name == "state_5.sqlite" for path in backups_root.rglob("*") if path.is_file()))
            self.assertTrue(any(path.name == "session_index.jsonl" for path in backups_root.rglob("*") if path.is_file()))
            self.assertTrue(
                any(path.name == target_rollout.name for path in backups_root.rglob("*") if path.is_file())
            )
            self.assertTrue(
                any(path.name == broken_rollout.name for path in backups_root.rglob("*") if path.is_file())
            )


if __name__ == "__main__":
    unittest.main()
