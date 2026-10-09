"""Exercise the installed native lifecycle, hook dispatcher and completion handler."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ["HERMES_AGENT_ROOT"])
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(PLUGIN_DIR / "tests" / "fixtures"))

from hermes_cli import kanban_db as native
from hermes_cli import kanban_db_connect as connections
from hermes_cli import plugins as native_plugins
from tools import kanban_tools
import exact_review_guard as guard

spec = importlib.util.spec_from_file_location("review_recording_native_fixture", PLUGIN_DIR / "__init__.py")
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

SHA = "a" * 40


class NativeCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(os.environ["TMPDIR"])
        self.temp = tempfile.TemporaryDirectory(prefix="review-recording-native-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.db = self.home / "kanban" / "boards" / "fixture" / "kanban.db"
        self.environment = patch.dict(os.environ, {
            "HERMES_HOME": str(self.home), "HERMES_KANBAN_HOME": str(self.home),
            "HERMES_KANBAN_BOARD": "fixture", "HERMES_KANBAN_DB": str(self.db),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.conn = connections.connect(board="fixture")
        self.addCleanup(self.conn.close)
        self.task = native.create_task(self.conn, title="Recording fixture", assignee="builder", board="fixture")
        self.assertIsNotNone(native.claim_task(self.conn, self.task, claimer="fixture-builder"))
        builder_run = native.latest_run(self.conn, self.task)
        assert builder_run is not None
        self.builder = builder_run.id
        self.assertTrue(native.request_review(self.conn, self.task, reviewer="reviewer", summary="Ready for independent review", metadata={"commit": SHA}, expected_run_id=self.builder))
        self.assertIsNotNone(native.claim_review_task(self.conn, self.task, claimer="fixture-reviewer"))
        reviewer_run = native.latest_run(self.conn, self.task)
        assert reviewer_run is not None
        self.reviewer = reviewer_run.id
        os.environ.update({"HERMES_KANBAN_TASK": self.task, "HERMES_KANBAN_RUN_ID": str(self.reviewer)})
        self.policy = self.home / "kanban" / "delivery-policy.json"
        self.policy.write_text(json.dumps({"policy_version": 2, "boards": {"fixture": {
            "mode": "git", "review": {"required": True, "allowed_profiles": ["reviewer"]},
        }}}))

    def dispatch_completion(self, args: dict) -> dict:
        # Use the real plugin callback manager and native argument-merging path,
        # then call the same handler used by the model-facing kanban_complete tool.
        manager = native_plugins.PluginManager()
        manager._hooks["pre_tool_call"] = [plugin._pre_tool_call]
        with patch.object(native_plugins, "_delivery_manager", return_value=manager):
            message, modified = native_plugins._dispatch_pre_tool_call_hooks("kanban_complete", args)
        if message is not None:
            return {"blocked": True, "message": message}
        return json.loads(kanban_tools._handle_complete(modified or args))

    def test_real_native_review_completion_records_exact_approval(self) -> None:
        original = {"task_id": self.task, "summary": "The review is sound. Free prose is sufficient.", "metadata": {"note": "retained"}}
        result = self.dispatch_completion(original)
        self.assertTrue(result.get("ok"), result)
        task = native.get_task(self.conn, self.task)
        assert task is not None
        self.assertEqual(task.status, "done")
        verdict = native.latest_run(self.conn, self.task)
        assert verdict is not None and verdict.metadata is not None
        metadata = verdict.metadata if isinstance(verdict.metadata, dict) else json.loads(verdict.metadata)
        self.assertEqual(metadata["reviewed_commit"], SHA)
        self.assertIs(metadata["approved"], True)
        self.assertEqual(metadata["review_outcome"], "approved")
        self.assertEqual(metadata["note"], "retained")
        self.assertNotIn("approved", original["metadata"])
        result = guard.verify_exact_review(self.conn, self.task, SHA, {"reviewer"})
        self.assertTrue(result["approved"], result)

    def test_without_plugin_native_completion_reproduces_original_failure(self) -> None:
        result = json.loads(kanban_tools._handle_complete({"task_id": self.task, "summary": "Approved exact candidate; ordinary prose."}))
        self.assertTrue(result.get("ok"), result)
        result = guard.verify_exact_review(self.conn, self.task, SHA, {"reviewer"})
        self.assertFalse(result["approved"], result)
        self.assertEqual(result["reason"], "verdict_sha_mismatch")

    def test_contradiction_blocks_before_native_completion(self) -> None:
        result = self.dispatch_completion({"task_id": self.task, "summary": "Report prose", "metadata": {"approved": False}})
        self.assertTrue(result.get("blocked"), result)
        task = native.get_task(self.conn, self.task)
        assert task is not None
        self.assertEqual(task.status, "running")
        self.assertEqual(task.current_run_id, self.reviewer)

    def test_wrong_sha_cannot_be_silently_rebound(self) -> None:
        result = self.dispatch_completion({"task_id": self.task, "summary": "Report prose", "metadata": {"reviewed_commit": "b" * 40}})
        self.assertTrue(result.get("blocked"), result)
        task = native.get_task(self.conn, self.task)
        assert task is not None
        self.assertEqual(task.status, "running")


if __name__ == "__main__":
    unittest.main()
