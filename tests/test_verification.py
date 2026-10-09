"""Regressions for fail-closed native test-source selection."""
from __future__ import annotations

import importlib.util
import os
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


if __name__ == "__main__":
    unittest.main()
