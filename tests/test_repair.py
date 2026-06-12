import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_session_doctor.paths import CodexPaths
from codex_session_doctor.repair import rebuild_session_index, repair_previews, sync_provider_model


class RepairTests(unittest.TestCase):
    def make_paths(self, root: Path) -> CodexPaths:
        return CodexPaths(
            codex_home=root,
            config_path=root / "config.toml",
            db_path=root / "state_5.sqlite",
            session_index_path=root / "session_index.jsonl",
            sessions_dir=root / "sessions",
            archived_sessions_dir=root / "archived_sessions",
            backup_dir=root / "session_doctor_backups",
        )

    def init_db(self, db_path: Path) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            create table threads (
                id text primary key,
                title text,
                cwd text,
                rollout_path text,
                source text,
                model_provider text,
                model text,
                archived integer,
                updated_at integer,
                first_user_message text,
                preview text
            )
            """
        )
        conn.execute(
            """
            insert into threads values (
                't1', 'Title', '\\\\?\\C:\\Project', '', 'vscode', '0_1',
                'gpt-5.5', 0, 10, 'First message', ''
            )
            """
        )
        conn.commit()
        conn.close()

    def init_db_with_rollout(self, paths: CodexPaths) -> Path:
        rollout = paths.sessions_dir / "2026" / "06" / "12" / "rollout-test-t1.jsonl"
        rollout.parent.mkdir(parents=True, exist_ok=True)
        first_line = {
            "type": "session_meta",
            "payload": {
                "id": "t1",
                "cwd": r"C:\Project",
                "model_provider": "old-provider",
                "model": "old-model",
            },
        }
        rollout.write_text(json.dumps(first_line, ensure_ascii=False) + "\n{}\n", encoding="utf-8")

        conn = sqlite3.connect(paths.db_path)
        conn.execute(
            """
            create table threads (
                id text primary key,
                title text,
                cwd text,
                rollout_path text,
                source text,
                model_provider text,
                model text,
                archived integer,
                updated_at integer,
                first_user_message text,
                preview text
            )
            """
        )
        conn.execute(
            """
            insert into threads values (
                't1', 'Title', '\\\\?\\C:\\Project', ?, 'vscode', 'old-provider',
                'old-model', 0, 10, 'First message', 'First message'
            )
            """,
            (str(rollout),),
        )
        conn.commit()
        conn.close()
        return rollout

    def test_repair_previews(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            self.init_db(paths.db_path)
            changes = repair_previews(paths, dry_run=False)
            self.assertEqual(1, len(changes))
            conn = sqlite3.connect(paths.db_path)
            preview = conn.execute("select preview from threads where id='t1'").fetchone()[0]
            conn.close()
            self.assertEqual("First message", preview)

    def test_rebuild_session_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            self.init_db(paths.db_path)
            changes = rebuild_session_index(paths, dry_run=False)
            self.assertEqual(["session_index.jsonl <- 1 entries (was 0)"], changes)
            item = json.loads(paths.session_index_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("t1", item["id"])
            self.assertEqual("Title", item["thread_name"])

    def test_sync_provider_model_updates_database_and_session_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            rollout = self.init_db_with_rollout(paths)
            changes = sync_provider_model(paths, "0_1", "gpt-5.5", dry_run=False)
            self.assertEqual(2, len(changes))

            conn = sqlite3.connect(paths.db_path)
            row = conn.execute("select model_provider, model from threads where id='t1'").fetchone()
            conn.close()
            self.assertEqual(("0_1", "gpt-5.5"), row)

            first_line = json.loads(rollout.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("0_1", first_line["payload"]["model_provider"])
            self.assertEqual("gpt-5.5", first_line["payload"]["model"])


if __name__ == "__main__":
    unittest.main()
