from __future__ import annotations

import argparse

from . import __version__
from .bot import CodexTelegramBot, StartupCheckError
from .check_env import run_environment_check_from_path
from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Codex dispatcher.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run environment checks and exit.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to config.json. Defaults to BOT_CONFIG or ./config.json.",
    )
    args = parser.parse_args()

    if args.check:
        code, text = run_environment_check_from_path(args.config)
        print(text)
        raise SystemExit(code)

    config = load_config(args.config)
    bot = CodexTelegramBot(config)
    try:
        bot.run_forever()
    except StartupCheckError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
