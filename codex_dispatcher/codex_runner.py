from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountManager
from .config import AppConfig
from .state import StateStore


SANDBOX_MODES = {"read-only", "workspace-write", "danger-full-access"}


@dataclass
class CodexRunResult:
    success: bool
    limit_detected: bool
    returncode: int
    account_name: str
    session_id: str | None
    final_message: str
    stdout: str
    stderr: str


def detect_limit(text: str, markers: tuple[str, ...]) -> bool:
    haystack = text.lower()
    return any(marker.lower() in haystack for marker in markers)


def extract_run_details(stdout: str | None) -> tuple[str | None, str | None]:
    session_id: str | None = None
    final_message: str | None = None
    if not stdout:
        return session_id, final_message
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            session_id = event["thread_id"]
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                final_message = text.strip()
    return session_id, final_message


class CodexService:
    def __init__(self, config: AppConfig, state: StateStore, accounts: AccountManager) -> None:
        self.config = config
        self.state = state
        self.accounts = accounts
        self.codex_binary = self._resolve_binary_path(config.codex.binary)

    @staticmethod
    def _resolve_binary_path(binary: str) -> str:
        if Path(binary).is_file():
            return binary
        resolved = shutil.which(binary)
        if resolved:
            return resolved
        raise FileNotFoundError(
            f"Codex binary was not found: {binary}. "
            "Set codex.binary in config.json to the full path of codex.exe."
        )

    def _base_command(self) -> list[str]:
        return [
            self.codex_binary,
            "--config",
            f'cli_auth_credentials_store="{self.config.codex.cli_auth_credentials_store}"',
        ]

    def _build_exec_command(
        self,
        *,
        prompt: str,
        output_path: Path,
        session_id: str | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        sandbox_mode: str | None = None,
    ) -> list[str]:
        command = self._base_command()
        if reasoning_effort:
            command += ["--config", f'model_reasoning_effort="{reasoning_effort}"']
        command += ["exec"]
        if session_id:
            command.append("resume")
            command += self._resume_sandbox_args(sandbox_mode)
        else:
            command += self._exec_sandbox_args(sandbox_mode)
        command += ["--json", "--output-last-message", str(output_path)]
        if model:
            command += ["--model", model]
        command += list(self.config.codex.extra_args)
        if session_id:
            command.append(session_id)
        command.append(prompt)
        return command

    def _exec_sandbox_args(self, sandbox_mode: str | None) -> list[str]:
        if not sandbox_mode:
            return []
        if sandbox_mode not in SANDBOX_MODES:
            raise ValueError(f"Unsupported sandbox mode: {sandbox_mode}")
        return ["--sandbox", sandbox_mode]

    def _resume_sandbox_args(self, sandbox_mode: str | None) -> list[str]:
        if not sandbox_mode or sandbox_mode == "read-only":
            return []
        if sandbox_mode == "workspace-write":
            return ["--full-auto"]
        if sandbox_mode == "danger-full-access":
            return ["--dangerously-bypass-approvals-and-sandbox"]
        raise ValueError(f"Unsupported sandbox mode for resume: {sandbox_mode}")

    def _run_once(
        self,
        *,
        prompt: str,
        session_id: str | None,
        account_name: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        sandbox_mode: str | None = None,
    ) -> CodexRunResult:
        self.accounts.prepare_account_files(account_name)

        with tempfile.TemporaryDirectory(prefix="codex-bot-") as temp_dir_name:
            output_path = Path(temp_dir_name) / "final_message.txt"
            env = os.environ.copy()
            env["CODEX_HOME"] = str(self.config.codex.state_dir)

            try:
                process = subprocess.run(
                    self._build_exec_command(
                        prompt=prompt,
                        output_path=output_path,
                        session_id=session_id,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        sandbox_mode=sandbox_mode,
                    ),
                    cwd=self.config.codex.cwd,
                    env=env,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=self.config.codex.response_timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return CodexRunResult(
                    success=False,
                    limit_detected=False,
                    returncode=-1,
                    account_name=account_name,
                    session_id=session_id,
                    final_message=(
                        "Codex run timed out after "
                        f"{self.config.codex.response_timeout_seconds} seconds."
                    ),
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                )

            stdout_text = process.stdout or ""
            stderr_text = process.stderr or ""
            parsed_session_id, parsed_final_message = extract_run_details(stdout_text)
            final_message = ""
            if output_path.exists():
                final_message = output_path.read_text(encoding="utf-8").strip()
            if not final_message and parsed_final_message:
                final_message = parsed_final_message
            if not final_message and stderr_text.strip():
                final_message = stderr_text.strip()
            if not final_message:
                final_message = stdout_text.strip() or "Codex finished without a final message."

            combined_output = "\n".join(
                part for part in (stdout_text, stderr_text, final_message) if part
            )
            limit_detected = detect_limit(combined_output, self.config.codex.limit_markers)
            success = process.returncode == 0 and not limit_detected

            return CodexRunResult(
                success=success,
                limit_detected=limit_detected,
                returncode=process.returncode,
                account_name=account_name,
                session_id=parsed_session_id or session_id,
                final_message=final_message,
                stdout=stdout_text,
                stderr=stderr_text,
            )

    @staticmethod
    def _build_continue_prompt(original_prompt: str) -> str:
        return (
            "Continue the previous unfinished Codex task after an interrupted run. "
            "Finish the same work and provide the final answer.\n\n"
            f"Original user request:\n{original_prompt}"
        )

    def run_prompt(self, *, chat_id: int, alias: str, prompt: str) -> CodexRunResult:
        thread = self.state.get_thread(chat_id, alias)
        session_id = thread.get("session_id")
        model = self._resolve_model(thread)
        reasoning_effort = self._resolve_reasoning_effort(thread)
        sandbox_mode = self._resolve_sandbox_mode(thread)
        preferred_account = self.accounts.get_active_account_name()
        attempted: list[str] = []
        next_prompt = prompt

        while True:
            attempted.append(preferred_account)
            result = self._run_once(
                prompt=next_prompt,
                session_id=session_id,
                account_name=preferred_account,
                model=model,
                reasoning_effort=reasoning_effort,
                sandbox_mode=sandbox_mode,
            )

            session_id = result.session_id or session_id
            if session_id:
                self.state.update_thread(
                    chat_id,
                    alias,
                    session_id=session_id,
                    account_name=result.account_name,
                )

            if result.success:
                self.state.update_thread(
                    chat_id,
                    alias,
                    session_id=session_id,
                    account_name=result.account_name,
                )
                self.state.set_active_account(result.account_name)
                return result

            if not self.config.codex.auto_switch_on_limit or not result.limit_detected:
                return result

            next_account = self.accounts.next_account_name(preferred_account, attempted=attempted)
            if next_account is None:
                return result

            preferred_account = next_account
            next_prompt = self._build_continue_prompt(prompt) if session_id else prompt

    def _resolve_model(self, thread: dict[str, object]) -> str | None:
        thread_model = thread.get("model") if isinstance(thread, dict) else None
        if isinstance(thread_model, str):
            normalized = thread_model.strip()
            if normalized and normalized.lower() not in {"default", "clear", "none", "off"}:
                return normalized
        if isinstance(self.config.codex.model, str):
            normalized = self.config.codex.model.strip()
            if normalized and normalized.lower() not in {"default", "clear", "none", "off"}:
                return normalized
        return None

    @staticmethod
    def _resolve_reasoning_effort(thread: dict[str, object]) -> str | None:
        reasoning_effort = thread.get("reasoning_effort") if isinstance(thread, dict) else None
        if isinstance(reasoning_effort, str):
            normalized = reasoning_effort.strip()
            if normalized and normalized.lower() not in {"default", "clear", "none", "off"}:
                return normalized
        return None

    @staticmethod
    def _resolve_sandbox_mode(thread: dict[str, object]) -> str | None:
        sandbox_mode = thread.get("sandbox_mode") if isinstance(thread, dict) else None
        if isinstance(sandbox_mode, str):
            normalized = sandbox_mode.strip()
            if normalized and normalized.lower() not in {"default", "clear", "none", "off"}:
                return normalized
        return None
