"""Regressions for fail-closed native test-source selection."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recording_verifier_fixture", ROOT / "scripts" / "verify.py")
assert spec and spec.loader
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class VerificationTests(unittest.TestCase):
    def test_missing_source_is_refused_without_subprocess(self) -> None:
        with patch.dict(os.environ, {"HERMES_AGENT_ROOT": ""}), patch.object(verifier.subprocess, "check_output") as call:
            self.assertEqual(verifier.main(), 2)
            call.assert_not_called()

    def test_wrong_source_pin_is_refused_before_discovery(self) -> None:
        with patch.dict(os.environ, {"HERMES_AGENT_ROOT": str(ROOT)}), patch.object(verifier.subprocess, "check_output", return_value="b" * 40) as call:
            self.assertEqual(verifier.main(), 2)
            self.assertEqual(call.call_count, 1)

    def test_untracked_source_is_checked_and_refused(self) -> None:
        with patch.dict(os.environ, {"HERMES_AGENT_ROOT": str(ROOT)}), patch.object(verifier.subprocess, "check_output", side_effect=[verifier.HERMES_COMMIT, "?? injected_module.py\n"]) as call:
            self.assertEqual(verifier.main(), 2)
            self.assertEqual(call.call_args.args[0][-1], "--untracked-files=all")

    def test_nonexistent_source_is_a_clear_refusal(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as name:
            with patch.dict(os.environ, {"HERMES_AGENT_ROOT": str(Path(name) / "missing")}):
                self.assertEqual(verifier.main(), 2)

    def test_git_lookup_errors_are_clear_refusals(self) -> None:
        for error in (FileNotFoundError("git unavailable"), subprocess.CalledProcessError(128, ["git", "rev-parse", "HEAD"])):
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, {"HERMES_AGENT_ROOT": str(ROOT)}), patch.object(verifier.subprocess, "check_output", side_effect=error):
                self.assertEqual(verifier.main(), 2)

    def test_runtime_bundle_excludes_nested_scratch_and_native_checkout(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as name:
            source = Path(name) / "source"
            source.mkdir()
            for filename in ("plugin.yaml", "__init__.py"):
                (source / filename).write_text("fixture " + filename)
            nested = source / ".test-scratch"
            nested.mkdir()
            (source / ".hermes-runtime-source").mkdir()
            (source / ".git").mkdir()
            with patch.object(verifier, "ROOT", source):
                bundle = verifier.stage_runtime_bundle(nested)
            self.assertEqual({p.name for p in bundle.iterdir()}, {"plugin.yaml", "__init__.py"})
            for filename in ("plugin.yaml", "__init__.py"):
                self.assertEqual((bundle / filename).read_bytes(), (source / filename).read_bytes())


if __name__ == "__main__":
    unittest.main()
