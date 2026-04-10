from __future__ import annotations

import unittest

from codex_dispatcher.path_utils import (
    ensure_windows_extended_prefix,
    strip_windows_extended_prefix,
)


class PathUtilsTests(unittest.TestCase):
    def test_strip_windows_extended_prefix_handles_drive_path(self) -> None:
        self.assertEqual(
            strip_windows_extended_prefix(r"\\?\C:\tmp\rollout.jsonl"),
            r"C:\tmp\rollout.jsonl",
        )

    def test_strip_windows_extended_prefix_handles_unc_path(self) -> None:
        self.assertEqual(
            strip_windows_extended_prefix(r"\\?\UNC\server\share\rollout.jsonl"),
            r"\\server\share\rollout.jsonl",
        )

    def test_ensure_windows_extended_prefix_normalizes_drive_letter(self) -> None:
        self.assertEqual(
            ensure_windows_extended_prefix(r"c:\tmp\rollout.jsonl"),
            r"\\?\C:\tmp\rollout.jsonl",
        )

    def test_ensure_windows_extended_prefix_handles_unc_path(self) -> None:
        self.assertEqual(
            ensure_windows_extended_prefix(r"\\server\share\rollout.jsonl"),
            r"\\?\UNC\server\share\rollout.jsonl",
        )


if __name__ == "__main__":
    unittest.main()
