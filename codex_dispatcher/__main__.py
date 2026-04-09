from __future__ import annotations

import argparse

from .bot import CodexTelegramBot
from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Codex dispatcher.")
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to config.json. Defaults to BOT_CONFIG or ./config.json.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    bot = CodexTelegramBot(config)
    bot.run_forever()


if __name__ == "__main__":
    main()
