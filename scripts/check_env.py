from __future__ import annotations

import argparse

from codex_dispatcher.check_env import run_environment_check_from_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex Dispatcher environment checks.")
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to config.json. Defaults to BOT_CONFIG or ./config.json.",
    )
    args = parser.parse_args()

    code, text = run_environment_check_from_path(args.config)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
