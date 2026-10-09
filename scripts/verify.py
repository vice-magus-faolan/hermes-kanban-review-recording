#!/usr/bin/env python3
"""Run every isolated test and native plugin doctor against the pinned Hermes core."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HERMES_COMMIT = "f42f579cf8bac4918ac9599bece71618afadd846"


def main() -> int:
    """Refuse missing/wrong native source, skips, failing tests or failed doctor."""
    source_value = os.environ.get("HERMES_AGENT_ROOT")
    if not source_value:
        print("Set HERMES_AGENT_ROOT to a checkout of the documented Hermes commit.", file=sys.stderr)
        return 2
    source = Path(source_value).resolve(strict=True)
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True,
    ).strip()
    if actual != HERMES_COMMIT:
        print(f"Unsupported test source: {actual}; expected {HERMES_COMMIT}", file=sys.stderr)
        return 2
    # Dirty native files would defeat the exact-source compatibility assertion.
    changed = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True,
    ).strip()
    if changed:
        print("Native test source has tracked changes; use a clean checkout.", file=sys.stderr)
        return 2
    scratch = Path(os.environ.get("TMPDIR", ROOT / ".test-scratch")).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-recording-verify-", dir=scratch) as name:
        home = Path(name) / "home"
        home.mkdir()
        env = {
            "HERMES_HOME": str(home), "HERMES_DEFAULT_HOME": str(home),
            "HERMES_AGENT_ROOT": str(source), "TMPDIR": name,
        }
        with patch.dict(os.environ, env):
            sys.path.insert(0, str(source))
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
            count = suite.countTestCases()
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            if count < 25 or not result.wasSuccessful() or result.skipped:
                print(f"Verification refused: {count} tests, {len(result.skipped)} skips.")
                return 1
            # Preserve the current interpreter's admitted dependency paths and all
            # security/delegation markers; do not pip-edit a live Hermes generation.
            command = (
                "import sys,runpy; sys.path=" + repr(sys.path) + "; "
                "sys.argv=['hermes','plugins','doctor'," + repr(str(ROOT)) + ", '--ci']; "
                "runpy.run_module('hermes_cli.main',run_name='__main__',alter_sys=True)"
            )
            doctor = subprocess.run([sys.executable, "-c", command], cwd=name, check=False)
            if doctor.returncode:
                return doctor.returncode
    print(f"VERIFIED: {count} tests; zero skips; native plugin doctor passed; core={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
