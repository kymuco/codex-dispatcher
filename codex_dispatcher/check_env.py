from __future__ import annotations

from pathlib import Path

from .config import load_config
from .diagnostics import startup_report


def format_environment_report(report: dict[str, object], *, config_path: Path) -> str:
    lines = [
        "Environment check",
        "",
        f"Config: {config_path}",
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
                compact_issue = issue.replace("\n", " ")
                lines.append(f"- {compact_issue}")
    return "\n".join(lines)


def run_environment_check_from_path(config_path: str | None) -> tuple[int, str]:
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        return 1, f"Environment check failed: {exc}"

    report = startup_report(config)
    text = format_environment_report(report, config_path=config.config_path)
    return (0 if bool(report["ready"]) else 1), text
