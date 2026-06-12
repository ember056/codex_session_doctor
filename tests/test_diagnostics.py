import unittest

from codex_session_doctor.diagnostics import diagnose_threads
from codex_session_doctor.models import SessionMeta, ThreadRecord


def thread(**overrides):
    data = {
        "id": "t1",
        "title": "Hello",
        "cwd": r"\\?\C:\Project",
        "rollout_path": "",
        "source": "vscode",
        "model_provider": "0_1",
        "model": "gpt-5.5",
        "archived": 0,
        "updated_at": 1,
        "preview": "Hello",
        "first_user_message": "Hello",
    }
    data.update(overrides)
    return ThreadRecord(**data)


class DiagnosticTests(unittest.TestCase):
    def test_empty_preview_is_diagnosed(self):
        result = diagnose_threads([thread(preview="")], {}, {"t1"})
        self.assertIn("empty-preview", [item.code for item in result])

    def test_missing_index_is_diagnosed(self):
        result = diagnose_threads([thread()], {}, set())
        self.assertIn("missing-index-entry", [item.code for item in result])

    def test_cwd_mismatch_ignores_windows_long_path_prefix(self):
        meta = SessionMeta("t1", __file__, r"C:\Project", "0_1", "gpt-5.5")
        result = diagnose_threads([thread()], {"t1": meta}, {"t1"})
        self.assertNotIn("cwd-mismatch", [item.code for item in result])

    def test_cwd_mismatch_is_diagnosed(self):
        meta = SessionMeta("t1", __file__, r"C:\Other", "0_1", "gpt-5.5")
        result = diagnose_threads([thread()], {"t1": meta}, {"t1"})
        self.assertIn("cwd-mismatch", [item.code for item in result])

    def test_subagent_is_skipped_by_default(self):
        result = diagnose_threads([thread(source='{"subagent":{"other":"guardian"}}', preview="")], {}, set())
        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
