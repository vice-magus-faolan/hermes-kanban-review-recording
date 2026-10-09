"""Record approval metadata only for an authorized native review completion."""
from __future__ import annotations

from contextlib import closing
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

_FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")
_BOARD = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z")
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_BLOCK = "kanban review approval refused: "


def _deny(reason: str) -> dict[str, Any]:
    return {"action": "block", "message": _BLOCK + reason}


def _json_object(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        obj = json.loads(value)
    except (ValueError, TypeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _context() -> tuple[str, str, int, str, Path] | None:
    """Read dispatcher-pinned identity and validate canonical DB layout."""
    task = os.environ.get("HERMES_KANBAN_TASK", "")
    board = os.environ.get("HERMES_KANBAN_BOARD", "")
    raw_run = os.environ.get("HERMES_KANBAN_RUN_ID", "")
    raw_db = os.environ.get("HERMES_KANBAN_DB", "")
    if not (task and board and raw_run and raw_db):
        return None
    if not _BOARD.fullmatch(board) or not task:
        raise ValueError("invalid worker task or board identity")
    try:
        run_id = int(raw_run)
    except ValueError as exc:
        raise ValueError("invalid worker run identity") from exc
    if run_id <= 0:
        raise ValueError("invalid worker run identity")
    db = Path(raw_db).resolve(strict=True)
    # Native default board uses <shared-home>/kanban.db; named boards use
    # <shared-home>/kanban/boards/<board>/kanban.db.
    if board == "default" and db.name == "kanban.db":
        home = db.parent
    elif (db.name == "kanban.db" and db.parent.name == board
          and db.parent.parent.name == "boards"
          and db.parent.parent.parent.name == "kanban"):
        home = db.parent.parent.parent.parent
    else:
        raise ValueError("worker database path does not match pinned board")
    pinned_home = os.environ.get("HERMES_KANBAN_HOME")
    if pinned_home and Path(pinned_home).resolve(strict=True) != home:
        raise ValueError("worker database is outside pinned shared home")
    if not db.is_file():
        raise ValueError("worker database is not a file")
    return task, board, run_id, str(home / "kanban" / "delivery-policy.json"), db


def _policy(policy_path: str, board: str) -> tuple[bool, tuple[str, ...]]:
    try:
        raw = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        # No durable policy is an unconfigured board, never an implicit review gate.
        return False, ()
    if not isinstance(raw, dict) or raw.get("policy_version") != 2:
        raise ValueError("invalid delivery policy")
    boards = raw.get("boards")
    config = boards.get(board) if isinstance(boards, dict) else None
    # Unknown/non-Git boards are deliberately out of scope.
    if not isinstance(config, dict) or config.get("mode") != "git":
        return False, ()
    review = config.get("review")
    if not isinstance(review, dict) or set(review) != {"required", "allowed_profiles"}:
        raise ValueError("malformed board review policy")
    required, profiles = review.get("required"), review.get("allowed_profiles")
    if not isinstance(required, bool) or not isinstance(profiles, list):
        raise ValueError("malformed board review policy")
    if any(not isinstance(p, str) or not _PROFILE.fullmatch(p) for p in profiles) or len(set(profiles)) != len(profiles):
        raise ValueError("invalid authorized reviewer profile")
    if required and not profiles:
        raise ValueError("required review has no authorized reviewer")
    if not required and profiles:
        raise ValueError("non-required review cannot authorize reviewers")
    return required, tuple(profiles)


def _review_state(db: Path, task: str, run_id: int) -> tuple[str, str | None]:
    """Return scope plus latest handoff SHA, relying only on durable run/event data."""
    uri = "file:" + quote(str(db), safe="/") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
        row = conn.execute("SELECT status, current_run_id FROM tasks WHERE id = ?", (task,)).fetchone()
        if row is None:
            return "ordinary", None
        if row[0] != "running" or row[1] != run_id:
            return "ordinary", None
        run = conn.execute("SELECT id, profile, status, outcome, ended_at FROM task_runs WHERE id = ? AND task_id = ?", (run_id, task)).fetchone()
        if run is None or run[2] != "running" or run[3] is not None or run[4] is not None:
            return "ordinary", None
        claims = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed'", (task, run_id)).fetchall()
        if not any((lambda p: p.get("source_status") == "review" and p.get("run_id") == run_id)(_json_object(r[0])) for r in claims):
            return "ordinary", None
        # Latest successful review-request run is the only usable handoff.
        runs = conn.execute("SELECT id, profile, status, outcome, ended_at, metadata FROM task_runs WHERE task_id=? ORDER BY id", (task,)).fetchall()
        prior = [r for r in runs if r[0] < run_id]
        handoffs = [r for r in prior if r[3] == "review_requested" and r[4] is not None]
        if not handoffs:
            raise ValueError("review handoff is missing or stale")
        handoff = handoffs[-1]
        if handoff[2] != "review":
            raise ValueError("builder handoff has invalid native lifecycle status")
        if handoff[1] == run[1]:
            raise ValueError("reviewer is not independent of builder")
        if any(r[0] > handoff[0] and r[3] == "changes_requested" for r in prior):
            raise ValueError("review handoff was invalidated by requested changes")
        if not conn.execute("SELECT 1 FROM task_events WHERE task_id=? AND run_id=? AND kind='review_requested'", (task, handoff[0])).fetchone():
            raise ValueError("native review-request event is missing")
        sha = _json_object(handoff[5]).get("commit")
        if not isinstance(sha, str) or not _FULL_SHA.fullmatch(sha):
            raise ValueError("latest builder handoff has no valid full commit SHA")
        return "review", sha


def prepare_completion(args: dict[str, Any]) -> dict[str, Any] | None:
    """Return native hook directive; None means intentionally leave call unchanged."""
    if args.get("task_id") and args.get("task_id") != os.environ.get("HERMES_KANBAN_TASK"):
        return None
    env = os.environ.get("HERMES_KANBAN_TASK")
    if not env:
        return None
    metadata = args.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        return _deny("metadata must be an object")
    # Policy/path failures are fatal only once the configured board is in scope.
    try:
        context = _context()
    except (OSError, ValueError, sqlite3.Error) as exc:
        return _deny(str(exc))
    if context is None:
        return None
    task, board, run_id, policy_path, db = context
    try:
        required, allowed = _policy(policy_path, board)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _deny(f"cannot validate delivery policy: {exc}")
    if not required:
        return None
    try:
        scope, sha = _review_state(db, task, run_id)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return _deny(f"cannot validate active review run: {exc}")
    if scope == "ordinary":
        return None
    # Identity is the immutable run profile, checked below; task assignment and
    # model-provided identity fields are never consulted.
    with closing(sqlite3.connect("file:" + quote(str(db), safe="/") + "?mode=ro", uri=True, timeout=2)) as conn:
        reviewer_row = conn.execute("SELECT profile FROM task_runs WHERE id=? AND task_id=?", (run_id, task)).fetchone()
    reviewer = reviewer_row[0] if reviewer_row else None
    if reviewer not in allowed:
        return _deny("active reviewer is not authorized by durable board policy")
    if "approved" in metadata and metadata["approved"] is not True:
        return _deny("explicit approval metadata is contradictory")
    if "review_outcome" in metadata and metadata["review_outcome"] != "approved":
        return _deny("explicit review outcome is contradictory")
    if "reviewed_commit" in metadata and metadata["reviewed_commit"] != sha:
        return _deny("explicit reviewed commit does not match latest builder handoff")
    findings = metadata.get("blocking_findings")
    if findings not in (None, [], (), ""):
        return _deny("blocking findings are present")
    updated = dict(metadata)
    updated.update(approved=True, review_outcome="approved", reviewed_commit=sha)
    return {"action": "modify", "args": {"metadata": updated}}


def register(ctx: Any) -> None:
    ctx.register_hook("pre_tool_call", _pre_tool_call)


def _pre_tool_call(*, tool_name: str, args: dict[str, Any], **_: Any) -> dict[str, Any] | None:
    if tool_name != "kanban_complete":
        return None
    try:
        return prepare_completion(args)
    except Exception as exc:  # In-scope failures never silently fail open.
        return _deny(f"unexpected validation error: {type(exc).__name__}: {exc}")
