from __future__ import annotations

from pathlib import Path

from .config import AppConfig, load_config
from .core import DispatcherService
from .path_utils import display_path


def _check_failure_text(*, problem: str, fix: str) -> str:
    return "\n".join(
        [
            "Environment check failed.",
            f"Problem: {problem}",
            f"Fix: {fix}",
        ]
    )


def _load_config_failure_text(exc: Exception) -> str:
    problem = str(exc).strip().replace("\n", " ")
    if isinstance(exc, FileNotFoundError):
        return _check_failure_text(
            problem=problem,
            fix="Use a valid config path or copy config.example.json to config.json.",
        )
    return _check_failure_text(
        problem=problem,
        fix="Update the listed config field and run --check again.",
    )


def format_environment_report(report: dict[str, object], *, config_path: Path) -> str:
    lines = [
        "Environment check",
        "",
        f"Config: {display_path(config_path)}",
        f"Telegram token: {report['token']}",
        f"Codex binary: {report['codex_binary']}",
        f"Workspace: {report['workspace']}",
        f"State dir: {report['state_dir']}",
        f"Accounts: {report['accounts']}",
        "",
        f"Result: {'ready' if report['ready'] else 'not ready'}",
    ]
    issues = report.get("issues")
    if isinstance(issues, list) and issues:
        lines.append("Issues:")
        for issue in issues:
            if isinstance(issue, str):
                chunks = [line.strip() for line in issue.splitlines() if line.strip()]
                if not chunks:
                    continue
                lines.append(f"- {chunks[0]}")
                for chunk in chunks[1:]:
                    lines.append(f"  {chunk}")
    return "\n".join(lines)


def run_environment_check(config: AppConfig) -> tuple[int, str]:
    dispatcher = DispatcherService(config)
    report = dispatcher.startup_report()
    text = format_environment_report(report, config_path=config.config_path)
    return (0 if bool(report["ready"]) else 1), text


def run_environment_check_from_path(config_path: str | None) -> tuple[int, str]:
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        return 1, _load_config_failure_text(exc)

    return run_environment_check(config)
