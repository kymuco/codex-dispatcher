from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import codex_dispatcher.__main__ as cli
from codex_dispatcher import __version__, get_version


class CliTests(unittest.TestCase):
    def test_get_version_uses_fallback_when_metadata_missing(self) -> None:
        with patch("codex_dispatcher.metadata_version", side_effect=PackageNotFoundError):
            self.assertEqual(get_version(), "0.0.0+local")

    def test_main_prints_version_and_exits(self) -> None:
        output = io.StringIO()

        with patch("sys.argv", ["codex-dispatcher", "--version"]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(result.exception.code, 0)
        self.assertIn(__version__, output.getvalue())

    def test_main_check_mode_exits_with_report_code(self) -> None:
        output = io.StringIO()
        with (
            patch("codex_dispatcher.__main__.run_environment_check_from_path", return_value=(0, "Environment check")),
            patch("sys.argv", ["codex-dispatcher", "--check"]),
            redirect_stdout(output),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()

        self.assertEqual(result.exception.code, 0)
        self.assertIn("Environment check", output.getvalue())


if __name__ == "__main__":
    unittest.main()
