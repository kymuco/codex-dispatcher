from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import AppConfig
from .path_utils import display_path, normalize_rollout_path, strip_windows_extended_prefix
from .state import StateStore


THREAD_COLUMNS = (
    "id",
    "rollout_path",
    "created_at",
    "updated_at",
    "source",
    "model_provider",
    "cwd",
    "title",
    "sandbox_policy",
    "approval_mode",
    "tokens_used",
    "has_user_event",
    "archived",
    "archived_at",
    "git_sha",
    "git_branch",
    "git_origin_url",
    "cli_version",
    "first_user_message",
    "agent_nickname",
    "agent_role",
    "memory_mode",
    "model",
    "reasoning_effort",
    "agent_path",
)

THREADS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,
    sandbox_policy TEXT NOT NULL,
    approval_mode TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    has_user_event INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    archived_at INTEGER,
    git_sha TEXT,
    git_branch TEXT,
    git_origin_url TEXT,
    cli_version TEXT NOT NULL DEFAULT '',
    first_user_message TEXT NOT NULL DEFAULT '',
    agent_nickname TEXT,
    agent_role TEXT,
    memory_mode TEXT NOT NULL DEFAULT 'enabled',
    model TEXT,
    reasoning_effort TEXT,
    agent_path TEXT
)
"""

VIEW_COPY_PREFIX = "TEMP VIEW - "


@dataclass(frozen=True)
class SessionAttachment:
    source_session_id: str
    session_id: str
    target_file: Path
    imported: bool
    rekeyed: bool


@dataclass(frozen=True)
class SessionExport:
    session_id: str
    target_file: Path
    action: str


@dataclass(frozen=True)
class SessionClone:
    source_session_id: str
    cloned_session_id: str
    target_file: Path
    thread_name: str


@dataclass(frozen=True)
class SessionRepair:
    chat_id: int
    alias: str
    source_session_id: str
    repaired_session_id: str
    target_file: Path


class SessionManager:
    def __init__(self, config: AppConfig, state: StateStore) -> None:
        self.config = config
        self.state = state
        self.target_home = config.codex.state_dir
        self.vscode_home = Path.home() / ".codex"
        self.source_homes = [self.target_home, self.vscode_home]
        self.view_copy_registry_path = config.config_path.parent / "data" / "vscode_view_copies.json"
        self.view_rollouts_home = config.config_path.parent / "data" / "vscode_view_home"
        self.backups_home = config.config_path.parent / "backups"
        self.view_copy_registry_path.parent.mkdir(parents=True, exist_ok=True)

    def repair_colliding_local_sessions(self) -> list[SessionRepair]:
        snapshot = self.state.snapshot()
        chats = snapshot.get("chats", {})
        if not isinstance(chats, dict):
            return []

        repairs_needed: list[tuple[int, str, str, Path]] = []
        for raw_chat_id, chat in chats.items():
            if not isinstance(raw_chat_id, str) or not isinstance(chat, dict):
                continue
            try:
                chat_id = int(raw_chat_id)
            except ValueError:
                continue
            threads = chat.get("threads", {})
            if not isinstance(threads, dict):
                continue
            for alias, thread in threads.items():
                if not isinstance(alias, str) or not isinstance(thread, dict):
                    continue
                session_id = thread.get("session_id")
                if not isinstance(session_id, str) or not session_id.strip():
                    continue
                target_file = self._find_session_file_in_home(self.target_home, session_id)
                source_file = self._find_session_file_in_home(self.vscode_home, session_id)
                if target_file is None or source_file is None:
                    continue
                repairs_needed.append((chat_id, alias, session_id, target_file))

        if not repairs_needed:
            return []

        backup_stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        self._backup_runtime_state(backup_stamp)

        repairs: list[SessionRepair] = []
        for chat_id, alias, session_id, target_file in repairs_needed:
            repaired_file, repaired_session_id = self._clone_session_into_home(
                source_file=target_file,
                source_session_id=session_id,
                target_home=self.target_home,
            )
            self.state.update_thread(chat_id, alias, session_id=repaired_session_id, account_name=None)
            repairs.append(
                SessionRepair(
                    chat_id=chat_id,
                    alias=alias,
                    source_session_id=session_id,
                    repaired_session_id=repaired_session_id,
                    target_file=repaired_file,
                )
            )
        return repairs

    def attach_to_alias(self, *, chat_id: int, alias: str, session_ref: str) -> SessionAttachment:
        source_file, source_session_id = self._resolve_session_ref(session_ref, prefer_external=True)
        if self._is_session_file_in_home(source_file, self.target_home):
            session_id = source_session_id
            target_file = source_file.resolve()
            imported = False
            rekeyed = False
            self._ensure_session_index_entry(
                source_file=source_file,
                target_file=target_file,
                session_id=session_id,
                target_home=self.target_home,
            )
        else:
            target_file, session_id = self._clone_session_into_home(
                source_file=source_file,
                source_session_id=source_session_id,
                target_home=self.target_home,
            )
            imported = True
            rekeyed = True

        self.state.update_thread(chat_id, alias, session_id=session_id, account_name=None)
        return SessionAttachment(
            source_session_id=source_session_id,
            session_id=session_id,
            target_file=target_file,
            imported=imported,
            rekeyed=rekeyed,
        )

    def export_alias_to_vscode(self, *, chat_id: int, alias: str) -> SessionExport:
        thread = self.state.get_thread(chat_id, alias)
        session_id = thread.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError(f"Local chat '{alias}' does not have a session id yet.")

        source_file, resolved_session_id = self._resolve_session_ref(session_id)
        target_file, action = self._export_session_file(
            source_file,
            session_id=resolved_session_id,
            target_home=self.vscode_home,
            mirror_subdir="telegram-bot",
            overwrite_existing=False,
        )
        return SessionExport(session_id=resolved_session_id, target_file=target_file, action=action)

    def sync_alias_to_vscode(self, *, chat_id: int, alias: str) -> SessionExport:
        thread = self.state.get_thread(chat_id, alias)
        session_id = thread.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError(f"Local chat '{alias}' does not have a session id yet.")

        source_file, resolved_session_id = self._resolve_session_ref(session_id)
        target_file, action = self._export_session_file(
            source_file,
            session_id=resolved_session_id,
            target_home=self.vscode_home,
            mirror_subdir="telegram-bot",
            overwrite_existing=True,
        )
        return SessionExport(session_id=resolved_session_id, target_file=target_file, action=action)

    def clone_alias_to_vscode(self, *, chat_id: int, alias: str, title: str | None = None) -> SessionClone:
        thread = self.state.get_thread(chat_id, alias)
        session_id = thread.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError(f"Local chat '{alias}' does not have a session id yet.")

        source_file, resolved_session_id = self._resolve_session_ref(session_id)
        cloned_session_id = str(uuid.uuid4())
        thread_name = self._build_view_title(alias=alias, title=title)
        cloned_rollout = self._clone_rollout_file(
            source_file=source_file,
            source_session_id=resolved_session_id,
            target_file=self._target_cloned_session_path(
                source_file,
                source_session_id=resolved_session_id,
                cloned_session_id=cloned_session_id,
                target_home=self.view_rollouts_home,
            ),
            cloned_session_id=cloned_session_id,
            sanitize_for_view=False,
        )
        source_thread_row = self._load_source_thread_row(source_file=source_file, session_id=resolved_session_id)
        cloned_row = self._build_cloned_thread_row(
            source_file=cloned_rollout,
            source_thread_row=source_thread_row,
            source_session_id=resolved_session_id,
            cloned_session_id=cloned_session_id,
            thread_name=thread_name,
        )

        self._upsert_thread_row(self.vscode_home, cloned_row)
        self._append_session_index_entry(
            target_home=self.vscode_home,
            entry={
                "id": cloned_session_id,
                "thread_name": thread_name,
                "updated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        self._set_view_copy_registry_entry(
            cloned_session_id,
            {
                "source_session_id": resolved_session_id,
                "rollout_path": cloned_row["rollout_path"],
                "thread_name": thread_name,
                "source_rollout_path": str(source_file.resolve()),
                "created_at": datetime.now(tz=UTC).isoformat(),
            },
        )

        return SessionClone(
            source_session_id=resolved_session_id,
            cloned_session_id=cloned_session_id,
            target_file=cloned_rollout,
            thread_name=thread_name,
        )

    def delete_vscode_view_copy(self, cloned_session_id: str) -> Path:
        session_id = cloned_session_id.strip().strip('"').strip("'")
        if not session_id:
            raise ValueError("Cloned session id must not be empty.")

        registry = self._load_view_copy_registry()
        entry = registry.get(session_id)
        if not isinstance(entry, dict):
            raise ValueError(
                "Only cloned session ids created by /clonevscode can be deleted with this command."
            )

        self._delete_thread_row(self.vscode_home, session_id)
        self._remove_session_index_entry(self.vscode_home, session_id)
        self._remove_view_copy_registry_entry(session_id)
        rollout_path = entry.get("rollout_path")
        if not isinstance(rollout_path, str) or not rollout_path.strip():
            return Path(".")
        deleted_rollout = Path(self._strip_extended_prefix(rollout_path))
        if deleted_rollout.exists():
            deleted_rollout.unlink()
            self._cleanup_empty_parent_dirs(deleted_rollout.parent, stop_at=self.view_rollouts_home)
        return deleted_rollout

    def _resolve_session_ref(self, session_ref: str, *, prefer_external: bool = False) -> tuple[Path, str]:
        raw = session_ref.strip().strip('"').strip("'")
        if not raw:
            raise ValueError("Session reference must not be empty.")

        for path_candidate in self._session_ref_path_candidates(raw):
            if path_candidate.exists():
                if not path_candidate.is_file():
                    raise ValueError(f"Session path is not a file: {display_path(path_candidate)}")
                return path_candidate, self._extract_session_id_from_file(path_candidate)

        homes_to_search = self._ordered_source_homes(prefer_external=prefer_external)
        for home in homes_to_search:
            file = self._find_session_file_in_home(home, raw)
            if file is not None:
                return file, raw

        raise FileNotFoundError(
            f"Session not found for reference: {session_ref}. "
            "Pass either a full path to a session .jsonl file or a known session id."
        )

    def _session_ref_path_candidates(self, raw_ref: str) -> list[Path]:
        normalized = strip_windows_extended_prefix(raw_ref)
        path_candidate = Path(normalized).expanduser()
        candidates: list[Path] = [path_candidate]
        if not path_candidate.is_absolute():
            candidates.append((self.config.codex.cwd / path_candidate).expanduser())
            candidates.append((self.config.config_path.parent / path_candidate).expanduser())

        unique_candidates: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)
        return unique_candidates

    def _find_session_file_in_home(self, home: Path, session_id: str) -> Path | None:
        from_threads = self._find_rollout_from_threads_table(home, session_id)
        if from_threads is not None and from_threads.exists():
            return from_threads

        sessions_dir = home / "sessions"
        if sessions_dir.exists():
            direct_matches = sorted(sessions_dir.rglob(f"*{session_id}.jsonl"))
            if direct_matches:
                return direct_matches[0]

        index_path = home / "session_index.jsonl"
        if not index_path.exists():
            return None

        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("id") == session_id:
                if sessions_dir.exists():
                    named_matches = sorted(sessions_dir.rglob(f"*{session_id}.jsonl"))
                    if named_matches:
                        return named_matches[0]
                from_threads_retry = self._find_rollout_from_threads_table(home, session_id)
                if from_threads_retry is not None and from_threads_retry.exists():
                    return from_threads_retry
        return None

    def _find_rollout_from_threads_table(self, home: Path, session_id: str) -> Path | None:
        database_path = home / "state_5.sqlite"
        if not database_path.exists():
            return None

        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database_path)
            cursor = connection.cursor()
            if not self._table_exists(cursor, "threads"):
                return None
            cursor.execute("SELECT rollout_path FROM threads WHERE id = ? LIMIT 1", (session_id,))
            row = cursor.fetchone()
        except sqlite3.Error:
            return None
        finally:
            if connection is not None:
                connection.close()

        if row is None or not isinstance(row[0], str):
            return None
        raw_rollout_path = row[0].strip()
        if not raw_rollout_path:
            return None
        return Path(self._strip_extended_prefix(raw_rollout_path))

    def _extract_session_id_from_file(self, path: Path) -> str:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()
        if not first_line:
            raise ValueError(f"Session file is empty: {path}")

        try:
            first_event = json.loads(first_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Session file is not valid JSONL: {path}") from exc

        payload = first_event.get("payload")
        if (
            first_event.get("type") == "session_meta"
            and isinstance(payload, dict)
            and isinstance(payload.get("id"), str)
            and payload["id"].strip()
        ):
            return payload["id"].strip()

        raise ValueError(f"Could not find session id in: {path}")

    def _ordered_source_homes(self, *, prefer_external: bool) -> list[Path]:
        if not prefer_external:
            return list(self.source_homes)

        target_resolved = self.target_home.resolve()
        external_homes = [home for home in self.source_homes if home.resolve() != target_resolved]
        internal_homes = [home for home in self.source_homes if home.resolve() == target_resolved]
        return external_homes + internal_homes

    def _is_session_file_in_home(self, source_file: Path, home: Path) -> bool:
        try:
            source_file.resolve().relative_to((home / "sessions").resolve())
            return True
        except ValueError:
            return False

    def _import_session_file(
        self,
        source_file: Path,
        *,
        session_id: str,
        target_home: Path,
        mirror_subdir: str | None,
    ) -> tuple[Path, bool]:
        target_file = self._target_session_path(source_file, target_home=target_home, mirror_subdir=mirror_subdir)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        imported = source_file.resolve() != target_file.resolve()
        if imported:
            shutil.copy2(source_file, target_file)

        self._ensure_session_index_entry(
            source_file=source_file,
            target_file=target_file,
            session_id=session_id,
            target_home=target_home,
        )
        return target_file, imported

    def _export_session_file(
        self,
        source_file: Path,
        *,
        session_id: str,
        target_home: Path,
        mirror_subdir: str,
        overwrite_existing: bool,
    ) -> tuple[Path, str]:
        existing_file = self._find_session_file_in_home(target_home, session_id)
        if existing_file is not None:
            if not overwrite_existing:
                return existing_file, "exists"

            if source_file.resolve() != existing_file.resolve():
                existing_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, existing_file)
                self._ensure_session_index_entry(
                    source_file=source_file,
                    target_file=existing_file,
                    session_id=session_id,
                    target_home=target_home,
                )
                return existing_file, "updated"

            self._ensure_session_index_entry(
                source_file=source_file,
                target_file=existing_file,
                session_id=session_id,
                target_home=target_home,
            )
            return existing_file, "linked"

        target_file = self._target_session_path(
            source_file,
            target_home=target_home,
            mirror_subdir=mirror_subdir,
        )
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        self._ensure_session_index_entry(
            source_file=source_file,
            target_file=target_file,
            session_id=session_id,
            target_home=target_home,
        )
        return target_file, "created"

    def _target_session_path(
        self,
        source_file: Path,
        *,
        target_home: Path,
        mirror_subdir: str | None,
    ) -> Path:
        source_parts = list(source_file.parts)
        if "sessions" in source_parts:
            index = source_parts.index("sessions")
            relative_parts = source_parts[index + 1 :]
            if mirror_subdir:
                return target_home / "sessions" / mirror_subdir / Path(*relative_parts)
            return target_home / "sessions" / Path(*relative_parts)
        if mirror_subdir:
            return target_home / "sessions" / mirror_subdir / source_file.name
        return target_home / "sessions" / "imported" / source_file.name

    def _target_cloned_session_path(
        self,
        source_file: Path,
        *,
        source_session_id: str,
        cloned_session_id: str,
        target_home: Path,
    ) -> Path:
        source_parts = list(source_file.parts)
        target_name = self._build_cloned_filename(
            source_name=source_file.name,
            source_session_id=source_session_id,
            cloned_session_id=cloned_session_id,
        )
        if "sessions" in source_parts:
            index = source_parts.index("sessions")
            relative_parts = source_parts[index + 1 :]
            parent_parts = relative_parts[:-1]
            return target_home / "sessions" / Path(*parent_parts) / target_name
        return target_home / "sessions" / "imported" / target_name

    def _build_cloned_filename(
        self,
        *,
        source_name: str,
        source_session_id: str,
        cloned_session_id: str,
    ) -> str:
        source_path = Path(source_name)
        stem = source_path.stem
        if source_session_id in stem:
            cloned_stem = stem.replace(source_session_id, cloned_session_id)
        else:
            cloned_stem = f"{stem}-{cloned_session_id}"
        suffix = source_path.suffix or ".jsonl"
        return f"{cloned_stem}{suffix}"

    def _clone_session_into_home(
        self,
        *,
        source_file: Path,
        source_session_id: str,
        target_home: Path,
    ) -> tuple[Path, str]:
        cloned_session_id = str(uuid.uuid4())
        target_file = self._target_cloned_session_path(
            source_file,
            source_session_id=source_session_id,
            cloned_session_id=cloned_session_id,
            target_home=target_home,
        )
        cloned_file = self._clone_rollout_file(
            source_file=source_file,
            source_session_id=source_session_id,
            target_file=target_file,
            cloned_session_id=cloned_session_id,
        )

        source_thread_row = self._load_source_thread_row(source_file=source_file, session_id=source_session_id)
        source_index_entry = self._find_index_entry_near_file(source_file, source_session_id)
        thread_name = self._resolve_thread_name(
            source_index_entry=source_index_entry,
            source_thread_row=source_thread_row,
            fallback=cloned_file.stem,
        )
        imported_row = self._build_imported_thread_row(
            source_file=cloned_file,
            source_thread_row=source_thread_row,
            source_session_id=source_session_id,
            cloned_session_id=cloned_session_id,
            thread_name=thread_name,
        )
        self._upsert_thread_row(target_home, imported_row)
        self._append_session_index_entry(
            target_home=target_home,
            entry={
                "id": cloned_session_id,
                "thread_name": thread_name,
                "updated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        return cloned_file, cloned_session_id

    def _clone_rollout_file(
        self,
        *,
        source_file: Path,
        source_session_id: str,
        target_file: Path,
        cloned_session_id: str,
        sanitize_for_view: bool = False,
    ) -> Path:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        rewritten = False
        with source_file.open("r", encoding="utf-8") as source_handle, target_file.open(
            "w",
            encoding="utf-8",
        ) as target_handle:
            for raw_line in source_handle:
                line_to_write = raw_line
                keep_line = not sanitize_for_view
                if not rewritten:
                    try:
                        event = json.loads(raw_line)
                    except json.JSONDecodeError:
                        event = None
                    if (
                        isinstance(event, dict)
                        and event.get("type") == "session_meta"
                        and isinstance(event.get("payload"), dict)
                        and event["payload"].get("id") == source_session_id
                    ):
                        event["payload"]["id"] = cloned_session_id
                        line_to_write = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
                        rewritten = True
                        keep_line = True
                elif sanitize_for_view:
                    try:
                        event = json.loads(raw_line)
                    except json.JSONDecodeError:
                        event = None
                    keep_line = self._should_keep_sanitized_view_event(event)

                if keep_line:
                    target_handle.write(line_to_write)

        if not rewritten:
            target_file.unlink(missing_ok=True)
            raise ValueError(f"Could not rewrite session id inside rollout: {source_file}")
        return target_file.resolve()

    def _should_keep_sanitized_view_event(self, event: Any) -> bool:
        if not isinstance(event, dict):
            return False
        if event.get("type") != "response_item":
            return False
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return False
        if payload.get("type") != "message":
            return False
        role = payload.get("role")
        return role in {"user", "assistant"}

    def _load_source_thread_row(self, *, source_file: Path, session_id: str) -> dict[str, Any] | None:
        homes_to_try: list[Path] = []
        inferred_home = self._home_for_session_file(source_file)
        if inferred_home is not None:
            homes_to_try.append(inferred_home)
        homes_to_try.extend(self.source_homes)

        seen: set[Path] = set()
        for home in homes_to_try:
            resolved_home = home.resolve()
            if resolved_home in seen:
                continue
            seen.add(resolved_home)
            row = self._load_thread_row(home, session_id)
            if row is not None:
                return row
        return None

    def _home_for_session_file(self, source_file: Path) -> Path | None:
        resolved_file = source_file.resolve()
        for home in self.source_homes + [self.vscode_home]:
            sessions_root = (home / "sessions").resolve()
            try:
                resolved_file.relative_to(sessions_root)
                return home
            except ValueError:
                continue
        return None

    def _load_thread_row(self, home: Path, session_id: str) -> dict[str, Any] | None:
        database_path = home / "state_5.sqlite"
        if not database_path.exists():
            return None
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database_path)
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT {', '.join(THREAD_COLUMNS)} FROM threads WHERE id = ? LIMIT 1",
                (session_id,),
            )
            row = cursor.fetchone()
        except sqlite3.Error:
            return None
        finally:
            if connection is not None:
                connection.close()
        if row is None:
            return None
        return dict(zip(THREAD_COLUMNS, row, strict=True))

    def _build_cloned_thread_row(
        self,
        *,
        source_file: Path,
        source_thread_row: dict[str, Any] | None,
        source_session_id: str,
        cloned_session_id: str,
        thread_name: str,
    ) -> dict[str, Any]:
        now = int(datetime.now(tz=UTC).timestamp())
        row = dict(source_thread_row or {})
        row["id"] = cloned_session_id
        row["rollout_path"] = self._normalize_rollout_path(source_file)
        row["created_at"] = now
        row["updated_at"] = now
        row["source"] = "vscode"
        row["model_provider"] = row.get("model_provider") or "openai"
        row["cwd"] = row.get("cwd") or self._normalize_rollout_path(self.config.codex.cwd)
        row["title"] = thread_name
        row["sandbox_policy"] = row.get("sandbox_policy") or '{"type":"workspace-write"}'
        row["approval_mode"] = row.get("approval_mode") or "never"
        row["tokens_used"] = int(row.get("tokens_used") or 0)
        row["has_user_event"] = int(row.get("has_user_event") or 0)
        row["archived"] = 0
        row["archived_at"] = None
        row["git_sha"] = row.get("git_sha")
        row["git_branch"] = row.get("git_branch")
        row["git_origin_url"] = row.get("git_origin_url")
        row["cli_version"] = row.get("cli_version") or ""
        row["first_user_message"] = row.get("first_user_message") or source_session_id
        row["agent_nickname"] = row.get("agent_nickname")
        row["agent_role"] = row.get("agent_role")
        row["memory_mode"] = row.get("memory_mode") or "enabled"
        row["model"] = row.get("model")
        row["reasoning_effort"] = row.get("reasoning_effort")
        row["agent_path"] = row.get("agent_path")
        return {column: row.get(column) for column in THREAD_COLUMNS}

    def _build_imported_thread_row(
        self,
        *,
        source_file: Path,
        source_thread_row: dict[str, Any] | None,
        source_session_id: str,
        cloned_session_id: str,
        thread_name: str,
    ) -> dict[str, Any]:
        row = self._build_cloned_thread_row(
            source_file=source_file,
            source_thread_row=source_thread_row,
            source_session_id=source_session_id,
            cloned_session_id=cloned_session_id,
            thread_name=thread_name,
        )
        if source_thread_row is not None and source_thread_row.get("source"):
            row["source"] = source_thread_row["source"]
        return row

    def _resolve_thread_name(
        self,
        *,
        source_index_entry: dict[str, Any] | None,
        source_thread_row: dict[str, Any] | None,
        fallback: str,
    ) -> str:
        if isinstance(source_index_entry, dict):
            thread_name = source_index_entry.get("thread_name")
            if isinstance(thread_name, str) and thread_name.strip():
                return thread_name.strip()
        if isinstance(source_thread_row, dict):
            title = source_thread_row.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return fallback

    def _upsert_thread_row(self, home: Path, row: dict[str, Any]) -> None:
        database_path = home / "state_5.sqlite"
        database_path.parent.mkdir(parents=True, exist_ok=True)
        placeholders = ", ".join("?" for _ in THREAD_COLUMNS)
        columns_sql = ", ".join(THREAD_COLUMNS)
        values = [row[column] for column in THREAD_COLUMNS]
        connection = sqlite3.connect(database_path)
        try:
            cursor = connection.cursor()
            cursor.execute(THREADS_TABLE_SQL)
            cursor.execute(
                f"INSERT OR REPLACE INTO threads ({columns_sql}) VALUES ({placeholders})",
                values,
            )
            connection.commit()
        finally:
            connection.close()

    def _delete_thread_row(self, home: Path, session_id: str) -> None:
        database_path = home / "state_5.sqlite"
        if not database_path.exists():
            return
        connection = sqlite3.connect(database_path)
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM threads WHERE id = ?", (session_id,))
            connection.commit()
        finally:
            connection.close()

    def _table_exists(self, cursor: sqlite3.Cursor, table: str) -> bool:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1", (table,))
        return cursor.fetchone() is not None

    def _normalize_rollout_path(self, path: Path) -> str:
        return normalize_rollout_path(path)

    def _strip_extended_prefix(self, raw_path: str) -> str:
        return strip_windows_extended_prefix(raw_path)

    def _build_view_title(self, *, alias: str, title: str | None) -> str:
        base = (title or alias or "telegram view").strip()
        if base.upper().startswith(VIEW_COPY_PREFIX):
            return base
        return f"{VIEW_COPY_PREFIX}{base}"

    def _ensure_session_index_entry(
        self,
        *,
        source_file: Path,
        target_file: Path,
        session_id: str,
        target_home: Path,
    ) -> None:
        index_path = target_home / "session_index.jsonl"
        entries: list[dict[str, Any]] = []
        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)

        if any(entry.get("id") == session_id for entry in entries):
            return

        source_index_entry = self._find_index_entry_near_file(source_file, session_id)
        if source_index_entry is None:
            source_index_entry = {
                "id": session_id,
                "thread_name": target_file.stem,
                "updated_at": datetime.now(tz=UTC).isoformat(),
            }
        self._append_session_index_entry(target_home=target_home, entry=source_index_entry)

    def _append_session_index_entry(self, *, target_home: Path, entry: dict[str, Any]) -> None:
        index_path = target_home / "session_index.jsonl"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _remove_session_index_entry(self, home: Path, session_id: str) -> None:
        index_path = home / "session_index.jsonl"
        if not index_path.exists():
            return
        entries: list[str] = []
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entries.append(line)
                continue
            if isinstance(entry, dict) and entry.get("id") == session_id:
                continue
            entries.append(json.dumps(entry, ensure_ascii=False) if isinstance(entry, dict) else line)
        if entries:
            index_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        else:
            index_path.unlink()

    def _find_index_entry_near_file(self, source_file: Path, session_id: str) -> dict[str, Any] | None:
        parents = [source_file.parent]
        parents.extend(source_file.parents)
        for parent in parents:
            if parent.name != "sessions":
                continue
            home = parent.parent
            index_path = home / "session_index.jsonl"
            if not index_path.exists():
                continue
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("id") == session_id:
                    return entry
        return None

    def _load_view_copy_registry(self) -> dict[str, dict[str, Any]]:
        if not self.view_copy_registry_path.exists():
            return {}
        raw = json.loads(self.view_copy_registry_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, dict)}

    def _write_view_copy_registry(self, registry: dict[str, dict[str, Any]]) -> None:
        self.view_copy_registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _set_view_copy_registry_entry(self, session_id: str, entry: dict[str, Any]) -> None:
        registry = self._load_view_copy_registry()
        registry[session_id] = entry
        self._write_view_copy_registry(registry)

    def _remove_view_copy_registry_entry(self, session_id: str) -> None:
        registry = self._load_view_copy_registry()
        if session_id in registry:
            del registry[session_id]
            self._write_view_copy_registry(registry)

    def _cleanup_empty_parent_dirs(self, start_dir: Path, *, stop_at: Path) -> None:
        stop_resolved = stop_at.resolve()
        current = start_dir.resolve()
        while current != stop_resolved and current.exists():
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _backup_runtime_state(self, backup_stamp: str) -> None:
        targets = [
            self.state.path,
            self.target_home / "state_5.sqlite",
            self.target_home / "session_index.jsonl",
        ]
        self.backups_home.mkdir(parents=True, exist_ok=True)
        for source in targets:
            if not source.exists():
                continue
            backup_name = f"{source.name}.{backup_stamp}.bak"
            shutil.copy2(source, self.backups_home / backup_name)
