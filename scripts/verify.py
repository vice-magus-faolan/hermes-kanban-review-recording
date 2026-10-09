#!/usr/bin/env python3
"""Run every isolated test and native plugin doctor against the pinned Hermes core."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HERMES_COMMIT = "f42f579cf8bac4918ac9599bece71618afadd846"


def stage_runtime_bundle(directory: Path) -> Path:
    """Stage only manifest/runtime files, excluding checkout and scratch trees."""
    bundle = directory / "runtime-bundle"
    bundle.mkdir()
    for filename in ("plugin.yaml", "__init__.py"):
        shutil.copy2(ROOT / filename, bundle / filename)
    return bundle


def main() -> int:
    """Refuse missing/wrong native source, skips, failing tests or failed doctor."""
    source_value = os.environ.get("HERMES_AGENT_ROOT")
    if not source_value:
        print("Set HERMES_AGENT_ROOT to a checkout of the documented Hermes commit.", file=sys.stderr)
        return 2
    try:
        source = Path(source_value).resolve(strict=True)
        actual = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True,
        ).strip()
        if actual != HERMES_COMMIT:
            print(f"Unsupported test source: {actual}; expected {HERMES_COMMIT}", file=sys.stderr)
            return 2
        # Dirty/importable untracked files defeat exact-source compatibility.
        changed = subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"], text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Cannot validate native test source: {exc}", file=sys.stderr)
        return 2
    if changed:
        print("Native test source has tracked or untracked changes; use a clean checkout.", file=sys.stderr)
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
            # Invoke the real native CLI Doctor handler as a library, not the
            # product launcher, which can provision/repair a Hermes installation.
            # Doctor copies its target into a fixture below TMPDIR. Copying ROOT
            # recurses when TMPDIR is inside ROOT, and can vendor the core checkout.
            bundle = stage_runtime_bundle(Path(name))
            command = (
                "import sys; sys.path=" + repr(sys.path) + "; "
                "from hermes_cli.plugins_cmd import cmd_plugin_doctor; "
                "cmd_plugin_doctor(" + repr(str(bundle)) + ", ci=True)"
            )
            doctor = subprocess.run([sys.executable, "-c", command], cwd=name, check=False)
            if doctor.returncode:
                return doctor.returncode
    print(f"VERIFIED: {count} tests; zero skips; native plugin doctor passed; core={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
