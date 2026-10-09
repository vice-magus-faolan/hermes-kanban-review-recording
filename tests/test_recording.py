from __future__ import annotations

from contextlib import closing
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
spec = importlib.util.spec_from_file_location("kanban_review_recording_test", PLUGIN)
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
FIXTURE_DIR = PLUGIN.parent / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURE_DIR))
import exact_review_guard as exact_guard

SHA = "a" * 40
TASK = "t_fixture"


class RecordingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="review-recording-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / "worker-home"
        self.db = self.home / "kanban" / "boards" / "fixture" / "kanban.db"
        self.db.parent.mkdir(parents=True)
        self.policy = self.home / "kanban" / "delivery-policy.json"
        self.policy.parent.mkdir(parents=True, exist_ok=True)
        self.write_policy()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript("""
                CREATE TABLE tasks(id TEXT PRIMARY KEY, status TEXT, current_run_id INTEGER);
                CREATE TABLE task_runs(
                    id INTEGER PRIMARY KEY, task_id TEXT, profile TEXT, status TEXT,
                    outcome TEXT, ended_at INTEGER, metadata TEXT
                );
                CREATE TABLE task_events(
                    id INTEGER PRIMARY KEY, task_id TEXT, run_id INTEGER, kind TEXT, payload TEXT
                );
            """)
            conn.execute("INSERT INTO tasks VALUES (?, 'running', 2)", (TASK,))
            conn.execute("INSERT INTO task_runs VALUES (1, ?, 'builder', 'review', 'review_requested', 10, ?)",
                         (TASK, json.dumps({"commit": SHA})))
            conn.execute("INSERT INTO task_runs VALUES (2, ?, 'reviewer', 'running', NULL, NULL, '{}')", (TASK,))
            conn.executemany("INSERT INTO task_events VALUES (?, ?, ?, ?, ?)", [
                (1, TASK, 1, "review_requested", "{}"),
                (2, TASK, 2, "claimed", json.dumps({"source_status": "review", "run_id": 2})),
            ])
        self.old_env = {key: __import__("os").environ.get(key) for key in (
            "HERMES_KANBAN_TASK", "HERMES_KANBAN_RUN_ID", "HERMES_KANBAN_BOARD",
            "HERMES_KANBAN_DB", "HERMES_KANBAN_HOME",
        )}
        import os
        os.environ.update({
            "HERMES_KANBAN_TASK": TASK,
            "HERMES_KANBAN_RUN_ID": "2",
            "HERMES_KANBAN_BOARD": "fixture",
            "HERMES_KANBAN_DB": str(self.db),
            "HERMES_KANBAN_HOME": str(self.home),
        })
        self.addCleanup(self.restore_env)

    def restore_env(self) -> None:
        import os
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def write_policy(self, *, mode: str = "git", required: bool = True,
                     reviewers: list[str] | None = None) -> None:
        self.policy.write_text(json.dumps({
            "policy_version": 2,
            "boards": {"fixture": {
                "mode": mode,
                "review": {"required": required,
                           "allowed_profiles": ["reviewer"] if reviewers is None and required else (reviewers or [])},
            }},
        }))

    def complete(self, metadata: object = None) -> dict[str, Any]:
        args: dict[str, Any] = {"summary": "Approved after checking all requirements."}
        if metadata is not None:
            args["metadata"] = metadata
        result = plugin._pre_tool_call(tool_name="kanban_complete", args=args)
        self.assertIsNotNone(result)
        return result

    def test_approval_added_for_review_with_empty_metadata(self) -> None:
        self.assertEqual(self.complete({}), {"action": "modify", "args": {"metadata": {
            "approved": True, "review_outcome": "approved", "reviewed_commit": SHA,
        }}})

    def test_free_prose_without_metadata_is_preserved(self) -> None:
        original = {"summary": "Approved, with detailed free-form prose."}
        directive = plugin.prepare_completion(original)
        self.assertEqual(directive["args"]["metadata"], {
            "approved": True, "review_outcome": "approved", "reviewed_commit": SHA,
        })
        self.assertEqual(original, {"summary": "Approved, with detailed free-form prose."})

    def test_preserves_arbitrary_metadata_and_is_idempotent(self) -> None:
        metadata = {"tests_run": ["unit"], "custom": {"x": 1}}
        updated = self.complete(metadata)["args"]["metadata"]
        self.assertEqual(updated["tests_run"], ["unit"])
        self.assertEqual(updated["custom"], {"x": 1})
        self.assertEqual(self.complete(updated)["args"]["metadata"], updated)

    def test_contradictory_and_blocking_metadata_is_refused(self) -> None:
        for metadata in ({"approved": False}, {"approved": None},
                         {"review_outcome": "changes_requested"},
                         {"reviewed_commit": "b" * 40},
                         {"blocking_findings": ["issue"]}):
            with self.subTest(metadata=metadata):
                result = self.complete(metadata)
                self.assertEqual(result["action"], "block")
                self.assertIn("refused", result["message"])

    def test_matching_explicit_approval_metadata_is_preserved(self) -> None:
        metadata = {"approved": True, "review_outcome": "approved", "reviewed_commit": SHA}
        self.assertEqual(self.complete(metadata)["args"]["metadata"], metadata)

    def test_non_review_tool_is_untouched(self) -> None:
        self.assertIsNone(plugin._pre_tool_call(tool_name="kanban_comment", args={}))

    def test_ordinary_completion_with_non_review_claim_is_untouched(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE task_events SET payload=? WHERE run_id=2 AND kind='claimed'",
                         (json.dumps({"source_status": "ready", "run_id": 2}),))
        self.assertIsNone(plugin.prepare_completion({"summary": "builder work"}))

    def test_stale_active_run_is_untouched(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE tasks SET current_run_id=3 WHERE id=?", (TASK,))
        self.assertIsNone(plugin.prepare_completion({"summary": "stale"}))

    def test_cross_task_call_is_untouched(self) -> None:
        self.assertIsNone(plugin.prepare_completion({"task_id": "other", "summary": "other"}))

    def test_self_review_is_refused(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE task_runs SET profile='builder' WHERE id=2")
        result = self.complete({})
        self.assertEqual(result["action"], "block")
        self.assertIn("independent", result["message"])

    def test_unapproved_profile_is_refused(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE task_runs SET profile='outsider' WHERE id=2")
        result = self.complete({})
        self.assertEqual(result["action"], "block")
        self.assertIn("authorized", result["message"])

    def test_intervening_changes_request_invalidates_handoff(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE task_runs SET status='done', outcome='changes_requested', ended_at=12 WHERE id=2")
            conn.execute("UPDATE tasks SET current_run_id=4 WHERE id=?", (TASK,))
            conn.execute("INSERT INTO task_runs VALUES (4, ?, 'reviewer', 'running', NULL, NULL, '{}')", (TASK,))
            conn.execute("INSERT INTO task_events VALUES (3, ?, 4, 'claimed', ?)",
                         (TASK, json.dumps({"source_status": "review", "run_id": 4})))
        import os
        os.environ["HERMES_KANBAN_RUN_ID"] = "4"
        result = self.complete({})
        self.assertEqual(result["action"], "block")
        self.assertIn("invalidated", result["message"])

    def test_invalid_handoff_sha_is_refused(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE task_runs SET metadata=? WHERE id=1", (json.dumps({"commit": "not-a-sha"}),))
        result = self.complete({})
        self.assertEqual(result["action"], "block")
        self.assertIn("SHA", result["message"])

    def test_invalid_database_board_alignment_fails_closed(self) -> None:
        import os
        os.environ["HERMES_KANBAN_BOARD"] = "other"
        result = self.complete({})
        self.assertEqual(result["action"], "block")
        self.assertIn("path", result["message"])

    def test_unconfigured_and_non_git_board_are_untouched(self) -> None:
        self.write_policy(mode="none")
        self.assertIsNone(plugin.prepare_completion({"summary": "not configured"}))

    def test_review_not_required_is_untouched(self) -> None:
        self.write_policy(required=False)
        self.assertIsNone(plugin.prepare_completion({"summary": "review optional"}))

    def test_native_default_board_without_policy_is_untouched(self) -> None:
        import os
        default_db = self.home / "kanban.db"
        default_db.touch()
        os.environ.update({"HERMES_KANBAN_BOARD": "default", "HERMES_KANBAN_DB": str(default_db)})
        self.assertIsNone(plugin.prepare_completion({"summary": "ordinary inbox task"}))

    def test_missing_review_request_event_is_refused(self) -> None:
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM task_events WHERE run_id=1 AND kind='review_requested'")
        result = self.complete({})
        self.assertEqual(result["action"], "block")
        self.assertIn("event", result["message"])

    def test_exact_review_guard_red_to_green(self) -> None:
        # A completed immutable review lacking approval fields is rejected by the
        # exact-review guard; the hook's returned metadata makes the same receipt pass.
        directive = self.complete({})
        metadata = directive["args"]["metadata"]
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE tasks SET status='done', current_run_id=NULL WHERE id=?", (TASK,))
            conn.execute("UPDATE task_runs SET status='done', outcome='completed', ended_at=20, metadata='{}' WHERE id=2")
            conn.execute("INSERT INTO task_events VALUES (3, ?, 2, 'completed', '{}')", (TASK,))
            before = exact_guard.verify_exact_review(conn, TASK, SHA, {"reviewer"})
            self.assertFalse(before["approved"])
            conn.execute("UPDATE task_runs SET metadata=? WHERE id=2", (json.dumps(metadata),))
            after = exact_guard.verify_exact_review(conn, TASK, SHA, {"reviewer"})
            self.assertTrue(after["approved"], after)

    def test_native_pre_tool_hook_applies_modify_with_native_merge(self) -> None:
        from unittest.mock import patch
        hermes_source = Path(__import__("os").environ["HERMES_AGENT_ROOT"])
        self.assertTrue(hermes_source.is_dir())
        sys.path.insert(0, str(hermes_source))
        from hermes_cli import lifecycle
        from hermes_cli import plugins as native_plugins
        args = {"task_id": TASK, "summary": "Keep the review prose.", "metadata": {"note": "kept"}}
        callback = lambda **kwargs: plugin._pre_tool_call(**kwargs)
        with patch.object(lifecycle, "invoke_hook", side_effect=lambda _hook, **kwargs: [callback(**kwargs)]):
            directive = native_plugins._get_pre_tool_call_directive_details(
                tool_name="kanban_complete", args=args,
            )
        self.assertIsNone(directive.action)
        self.assertEqual(directive.modified_args["summary"], args["summary"])
        self.assertEqual(directive.modified_args["metadata"], {
            "note": "kept", "approved": True, "review_outcome": "approved", "reviewed_commit": SHA,
        })
        self.assertNotIn("approved", args["metadata"])

    def test_hook_registration_and_non_target_passthrough(self) -> None:
        class Context:
            def __init__(self) -> None:
                self.hooks: dict[str, Any] = {}
            def register_hook(self, name: str, callback: Any) -> None:
                self.hooks[name] = callback
        ctx = Context()
        plugin.register(ctx)
        self.assertEqual(set(ctx.hooks), {"pre_tool_call"})
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="kanban_show", args={}))


if __name__ == "__main__":
    unittest.main()
