import unittest

from codex_session_doctor.diagnostics import format_project_report, group_diagnoses_by_project, diagnose_threads
from codex_session_doctor.models import CurrentConfig, SessionMeta, ThreadRecord


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

    def test_provider_model_mismatch_is_diagnosed(self):
        meta = SessionMeta("t1", __file__, r"C:\Project", "old-provider", "old-model")
        result = diagnose_threads(
            [thread(model_provider="old-provider", model="old-model")],
            {"t1": meta},
            {"t1"},
            current_config=CurrentConfig(model_provider="0_1", model="gpt-5.5"),
        )
        codes = [item.code for item in result]
        self.assertIn("provider-mismatch", codes)
        self.assertIn("model-mismatch", codes)
        self.assertIn("session-provider-mismatch", codes)
        self.assertIn("session-model-mismatch", codes)

    def test_subagent_is_skipped_by_default(self):
        result = diagnose_threads([thread(source='{"subagent":{"other":"guardian"}}', preview="")], {}, set())
        self.assertEqual([], result)

    def test_group_project_report(self):
        threads = [
            thread(id="t1", title="One", cwd=r"\\?\C:\ProjectA", preview=""),
            thread(id="t2", title="Two", cwd=r"\\?\C:\ProjectA", preview="", rollout_path="x"),
            thread(id="t3", title="Three", cwd=r"\\?\C:\ProjectB", preview=""),
        ]
        diagnoses = diagnose_threads(threads, {}, {"t1", "t2", "t3"})
        groups = group_diagnoses_by_project(diagnoses, threads)
        report = format_project_report(groups)
        self.assertIn(r"项目目录: \\?\C:\ProjectA", report)
        self.assertIn("缺少侧边栏预览", report)
        self.assertEqual(2, len(groups))


if __name__ == "__main__":
    unittest.main()
