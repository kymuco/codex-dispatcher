from __future__ import annotations

import unittest

from codex_dispatcher.codex_runner import detect_limit, extract_run_details


class CodexRunnerTests(unittest.TestCase):
    def test_extract_run_details_reads_thread_id_and_final_message(self) -> None:
        stdout = """
{"type":"thread.started","thread_id":"thread-123"}
{"type":"item.completed","item":{"type":"agent_message","text":"First"}}
{"type":"item.completed","item":{"type":"agent_message","text":"Final answer"}}
""".strip()

        session_id, final_message = extract_run_details(stdout)

        self.assertEqual(session_id, "thread-123")
        self.assertEqual(final_message, "Final answer")

    def test_detect_limit_looks_for_any_marker(self) -> None:
        self.assertTrue(detect_limit("Error: usage limit reached", ("usage limit",)))
        self.assertFalse(detect_limit("Completed successfully", ("usage limit",)))

    def test_extract_run_details_tolerates_none_stdout(self) -> None:
        session_id, final_message = extract_run_details(None)
        self.assertIsNone(session_id)
        self.assertIsNone(final_message)


if __name__ == "__main__":
    unittest.main()
