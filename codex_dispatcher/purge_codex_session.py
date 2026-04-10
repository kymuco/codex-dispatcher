from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .path_utils import strip_windows_extended_prefix


@dataclass(frozen=True)
class SessionPurgeReport:
    session_id: str
    database_path: Path
    thread_row_exists: bool
    rollout_file: Path | None
    rollout_exists: bool
    index_entries_before: int
    stage1_outputs_before: int
    thread_dynamic_tools_before: int
    thread_spawn_edges_before: int
    assigned_thread_refs_before: int
    applied: bool = False
    backups: tuple[Path, ...] = ()
    thread_row_deleted: bool = False
    index_entries_removed: int = 0
    rollout_file_deleted: bool = False
    stage1_outputs_deleted: int = 0
    thread_dynamic_tools_deleted: int = 0
    thread_spawn_edges_deleted: int = 0
    assigned_thread_refs_cleared: int = 0


class CodexSessionPurger:
    def __init__(self, home: Path, *, backups_root: Path | None = None) -> None:
        self.home = home.expanduser().resolve()
        self.backups_root = (
            backups_root.expanduser().resolve()
            if backups_root is not None
            else Path(__file__).resolve().parents[1] / "backups"
        )
        self.backups_root.mkdir(parents=True, exist_ok=True)

    def inspect(self, session_id: str) -> SessionPurgeReport:
        session_id = self._normalize_session_id(session_id)
        database_path = self.home / "state_5.sqlite"
        index_path = self.home / "session_index.jsonl"

        thread_row = self._load_thread_row(database_path, session_id)
        rollout_file = self._find_rollout_file(session_id, thread_row=thread_row)

        return SessionPurgeReport(
            session_id=session_id,
            database_path=database_path,
            thread_row_exists=thread_row is not None,
            rollout_file=rollout_file,
            rollout_exists=rollout_file is not None and rollout_file.exists(),
            index_entries_before=self._count_index_entries(index_path, session_id),
            stage1_outputs_before=self._count_rows(database_path, "stage1_outputs", "thread_id", session_id),
            thread_dynamic_tools_before=self._count_rows(database_path, "thread_dynamic_tools", "thread_id", session_id),
            thread_spawn_edges_before=self._count_spawn_edge_rows(database_path, session_id),
            assigned_thread_refs_before=self._count_rows(
                database_path,
                "agent_job_items",
                "assigned_thread_id",
                session_id,
            ),
        )

    def purge(self, session_ids: Iterable[str]) -> list[SessionPurgeReport]:
        normalized_ids = self._dedupe(self._normalize_session_id(session_id) for session_id in session_ids)
        reports = [self.inspect(session_id) for session_id in normalized_ids]

        db_needed = any(
            report.thread_row_exists
            or report.stage1_outputs_before
            or report.thread_dynamic_tools_before
            or report.thread_spawn_edges_before
            or report.assigned_thread_refs_before
            for report in reports
        )
        index_needed = any(report.index_entries_before for report in reports)
        rollout_targets = self._dedupe(
            report.rollout_file.resolve() for report in reports if report.rollout_file is not None and report.rollout_exists
        )

        backups: list[Path] = []
        backup_stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        backup_root = self.backups_root / f"purge-{backup_stamp}"

        if db_needed:
            database_path = self.home / "state_5.sqlite"
            if database_path.exists():
                backups.append(self._backup_file(database_path, backup_root))

        if index_needed:
            index_path = self.home / "session_index.jsonl"
            if index_path.exists():
                backups.append(self._backup_file(index_path, backup_root))

        for rollout_file in rollout_targets:
            if rollout_file.exists():
                backups.append(self._backup_file(rollout_file, backup_root))

        db_deleted_counts = {session_id: (0, 0, 0, 0, 0) for session_id in normalized_ids}
        if db_needed:
            db_deleted_counts = self._purge_database(normalized_ids)

        if index_needed:
            self._rewrite_session_index(normalized_ids)

        for rollout_file in rollout_targets:
            if rollout_file.exists():
                rollout_file.unlink()
                self._cleanup_empty_parent_dirs(rollout_file.parent, stop_at=self.home / "sessions")

        backup_tuple = tuple(backups)
        applied_reports: list[SessionPurgeReport] = []
        for report in reports:
            deleted_counts = db_deleted_counts.get(report.session_id, (0, 0, 0, 0, 0))
            rollout_deleted_for_report = report.rollout_file is not None and report.rollout_file.resolve() in rollout_targets
            applied_reports.append(
                SessionPurgeReport(
                    session_id=report.session_id,
                    database_path=report.database_path,
                    thread_row_exists=report.thread_row_exists,
                    rollout_file=report.rollout_file,
                    rollout_exists=report.rollout_exists,
                    index_entries_before=report.index_entries_before,
                    stage1_outputs_before=report.stage1_outputs_before,
                    thread_dynamic_tools_before=report.thread_dynamic_tools_before,
                    thread_spawn_edges_before=report.thread_spawn_edges_before,
                    assigned_thread_refs_before=report.assigned_thread_refs_before,
                    applied=True,
                    backups=backup_tuple,
                    thread_row_deleted=deleted_counts[0] > 0,
                    index_entries_removed=report.index_entries_before,
                    rollout_file_deleted=rollout_deleted_for_report,
                    stage1_outputs_deleted=deleted_counts[1],
                    thread_dynamic_tools_deleted=deleted_counts[2],
                    thread_spawn_edges_deleted=deleted_counts[3],
                    assigned_thread_refs_cleared=deleted_counts[4],
                )
            )
        return applied_reports

    def _purge_database(self, session_ids: list[str]) -> dict[str, tuple[int, int, int, int, int]]:
        database_path = self.home / "state_5.sqlite"
        if not database_path.exists():
            return {session_id: (0, 0, 0, 0, 0) for session_id in session_ids}

        result: dict[str, tuple[int, int, int, int, int]] = {}
        connection = sqlite3.connect(database_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            cursor = connection.cursor()
            for session_id in session_ids:
                stage1_deleted = self._delete_rows(cursor, "stage1_outputs", "thread_id", session_id)
                tools_deleted = self._delete_rows(cursor, "thread_dynamic_tools", "thread_id", session_id)
                spawn_deleted = self._delete_spawn_edges(cursor, session_id)
                assigned_cleared = self._clear_assigned_thread_refs(cursor, session_id)
                thread_deleted = self._delete_rows(cursor, "threads", "id", session_id)
                result[session_id] = (
                    thread_deleted,
                    stage1_deleted,
                    tools_deleted,
                    spawn_deleted,
                    assigned_cleared,
                )
            connection.commit()
        finally:
            connection.close()
        return result

    def _rewrite_session_index(self, session_ids: list[str]) -> int:
        index_path = self.home / "session_index.jsonl"
        if not index_path.exists():
            return 0

        lines: list[str] = []
        removed = 0
        session_id_set = set(session_ids)
        for raw_line in index_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                lines.append(raw_line)
                continue
            if isinstance(entry, dict) and entry.get("id") in session_id_set:
                removed += 1
                continue
            lines.append(json.dumps(entry, ensure_ascii=False) if isinstance(entry, dict) else raw_line)

        if lines:
            index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            index_path.unlink()
        return removed

    def _count_index_entries(self, index_path: Path, session_id: str) -> int:
        if not index_path.exists():
            return 0
        count = 0
        for raw_line in index_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("id") == session_id:
                count += 1
        return count

    def _load_thread_row(self, database_path: Path, session_id: str) -> dict[str, Any] | None:
        if not database_path.exists():
            return None
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database_path)
            cursor = connection.cursor()
            if not self._table_exists(cursor, "threads"):
                return None
            cursor.execute("SELECT id, rollout_path FROM threads WHERE id = ? LIMIT 1", (session_id,))
            row = cursor.fetchone()
        except sqlite3.Error:
            return None
        finally:
            if connection is not None:
                connection.close()
        if row is None:
            return None
        return {"id": row[0], "rollout_path": row[1]}

    def _find_rollout_file(self, session_id: str, *, thread_row: dict[str, Any] | None) -> Path | None:
        if thread_row is not None:
            rollout_path = thread_row.get("rollout_path")
            if isinstance(rollout_path, str) and rollout_path.strip():
                candidate = Path(self._strip_extended_prefix(rollout_path))
                return candidate

        sessions_dir = self.home / "sessions"
        if not sessions_dir.exists():
            return None
        matches = sorted(sessions_dir.rglob(f"*{session_id}.jsonl"))
        if not matches:
            return None
        return matches[0]

    def _count_rows(self, database_path: Path, table: str, column: str, session_id: str) -> int:
        if not database_path.exists():
            return 0
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database_path)
            cursor = connection.cursor()
            if not self._table_exists(cursor, table):
                return 0
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (session_id,))
            row = cursor.fetchone()
        except sqlite3.Error:
            return 0
        finally:
            if connection is not None:
                connection.close()
        return int(row[0]) if row is not None else 0

    def _count_spawn_edge_rows(self, database_path: Path, session_id: str) -> int:
        if not database_path.exists():
            return 0
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database_path)
            cursor = connection.cursor()
            if not self._table_exists(cursor, "thread_spawn_edges"):
                return 0
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM thread_spawn_edges
                WHERE parent_thread_id = ? OR child_thread_id = ?
                """,
                (session_id, session_id),
            )
            row = cursor.fetchone()
        except sqlite3.Error:
            return 0
        finally:
            if connection is not None:
                connection.close()
        return int(row[0]) if row is not None else 0

    def _delete_rows(self, cursor: sqlite3.Cursor, table: str, column: str, session_id: str) -> int:
        if not self._table_exists(cursor, table):
            return 0
        cursor.execute(f"DELETE FROM {table} WHERE {column} = ?", (session_id,))
        return cursor.rowcount if cursor.rowcount != -1 else 0

    def _delete_spawn_edges(self, cursor: sqlite3.Cursor, session_id: str) -> int:
        if not self._table_exists(cursor, "thread_spawn_edges"):
            return 0
        cursor.execute(
            """
            DELETE FROM thread_spawn_edges
            WHERE parent_thread_id = ? OR child_thread_id = ?
            """,
            (session_id, session_id),
        )
        return cursor.rowcount if cursor.rowcount != -1 else 0

    def _clear_assigned_thread_refs(self, cursor: sqlite3.Cursor, session_id: str) -> int:
        if not self._table_exists(cursor, "agent_job_items"):
            return 0
        cursor.execute(
            "UPDATE agent_job_items SET assigned_thread_id = NULL WHERE assigned_thread_id = ?",
            (session_id,),
        )
        return cursor.rowcount if cursor.rowcount != -1 else 0

    def _table_exists(self, cursor: sqlite3.Cursor, table: str) -> bool:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1", (table,))
        return cursor.fetchone() is not None

    def _backup_file(self, source: Path, backup_root: Path) -> Path:
        backup_target = self._backup_target_for(source, backup_root)
        backup_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup_target)
        return backup_target

    def _backup_target_for(self, source: Path, backup_root: Path) -> Path:
        source_resolved = source.resolve()
        try:
            relative = source_resolved.relative_to(self.home)
        except ValueError:
            relative = Path(source_resolved.name)
        return backup_root / relative

    def _cleanup_empty_parent_dirs(self, start_dir: Path, *, stop_at: Path) -> None:
        stop_resolved = stop_at.resolve()
        current = start_dir.resolve()
        while current != stop_resolved and current.exists():
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _strip_extended_prefix(self, raw_path: str) -> str:
        return strip_windows_extended_prefix(raw_path)

    def _normalize_session_id(self, session_id: str) -> str:
        normalized = session_id.strip().strip('"').strip("'")
        if not normalized:
            raise ValueError("Session id must not be empty.")
        return normalized

    def _dedupe(self, values: Iterable[Any]) -> list[Any]:
        seen: set[Any] = set()
        unique: list[Any] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            unique.append(value)
        return unique


def format_report(report: SessionPurgeReport) -> str:
    status = "applied" if report.applied else "preview"
    lines = [
        f"[{status}] {report.session_id}",
        f"  db row: {'yes' if report.thread_row_exists else 'no'}",
        f"  rollout: {str(report.rollout_file) if report.rollout_file is not None else 'not found'}",
        f"  rollout exists: {'yes' if report.rollout_exists else 'no'}",
        f"  session_index entries: {report.index_entries_before}",
        f"  stage1_outputs: {report.stage1_outputs_before}",
        f"  thread_dynamic_tools: {report.thread_dynamic_tools_before}",
        f"  thread_spawn_edges: {report.thread_spawn_edges_before}",
        f"  assigned_thread_refs: {report.assigned_thread_refs_before}",
    ]
    if report.applied:
        lines.extend(
            [
                f"  backups: {len(report.backups)}",
                f"  thread row deleted: {'yes' if report.thread_row_deleted else 'no'}",
                f"  index entries removed: {report.index_entries_removed}",
                f"  rollout file deleted: {'yes' if report.rollout_file_deleted else 'no'}",
                f"  stage1_outputs deleted: {report.stage1_outputs_deleted}",
                f"  thread_dynamic_tools deleted: {report.thread_dynamic_tools_deleted}",
                f"  thread_spawn_edges deleted: {report.thread_spawn_edges_deleted}",
                f"  assigned_thread_refs cleared: {report.assigned_thread_refs_cleared}",
            ]
        )
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or purge a Codex session from a .codex home directory.",
    )
    parser.add_argument(
        "session_ids",
        nargs="+",
        help="One or more session ids to inspect or purge.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home() / ".codex",
        help="Path to the Codex home directory. Defaults to your local .codex folder.",
    )
    parser.add_argument(
        "--backups-root",
        type=Path,
        default=None,
        help="Directory for safety backups. Defaults to ./backups in this repository.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the selected session data. Without this flag the command only previews.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    purger = CodexSessionPurger(args.home, backups_root=args.backups_root)
    if not args.apply:
        for session_id in args.session_ids:
            print(format_report(purger.inspect(session_id)))
        return 0

    reports = purger.purge(args.session_ids)
    for report in reports:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
