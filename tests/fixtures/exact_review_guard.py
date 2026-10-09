"""Frozen pure exact-review consumer oracle, used only by isolated tests.

Copied without function-body changes from the original workspace guard.
See docs/provenance.md. This is not a deployed delivery guard.
"""
from __future__ import annotations
import json
import re
import sqlite3
from collections.abc import Collection
from typing import Any

FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")

def _metadata(value: object) -> dict[str, Any]:
    """Decode run metadata without exposing malformed or non-object values."""
    if not isinstance(value, str) or not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def native_review_event_error(
    connection: sqlite3.Connection,
    task_id: str,
    handoff_run_id: int,
    verdict_run_id: int,
) -> str | None:
    handoff_event = connection.execute(
        "SELECT 1 FROM task_events WHERE task_id = ? AND run_id = ? AND kind = 'review_requested'",
        (task_id, handoff_run_id),
    ).fetchone()
    if handoff_event is None:
        return "review_request_event_missing"
    claims = connection.execute(
        "SELECT payload FROM task_events WHERE task_id = ? AND run_id = ? AND kind = 'claimed'",
        (task_id, verdict_run_id),
    ).fetchall()
    review_claim = False
    for claim in claims:
        payload = _metadata(claim[0])
        if (
            payload.get("source_status") == "review"
            and payload.get("run_id") == verdict_run_id
        ):
            review_claim = True
            break
    if not review_claim:
        return "review_claim_event_missing"
    completed = connection.execute(
        "SELECT 1 FROM task_events WHERE task_id = ? AND run_id = ? AND kind = 'completed'",
        (task_id, verdict_run_id),
    ).fetchone()
    return None if completed is not None else "review_completion_event_missing"


def _latest_review_pair(
    connection: sqlite3.Connection, task_id: str
) -> tuple[tuple[Any, ...] | None, tuple[Any, ...] | None, str | None]:
    task = connection.execute(
        "SELECT status, current_run_id FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if task is None:
        return None, None, "task_missing"
    if task[0] != "done":
        return None, None, "task_not_done"
    if task[1] is not None:
        return None, None, "task_has_active_run"
    runs = connection.execute(
        """
        SELECT id, profile, status, outcome, ended_at, metadata
          FROM task_runs
         WHERE task_id = ?
         ORDER BY id
        """,
        (task_id,),
    ).fetchall()
    if any(run[4] is None for run in runs):
        return None, None, "active_run_present"
    if len(runs) < 2:
        return None, None, "review_pair_missing"
    verdict = tuple(runs[-1])
    if verdict[2] != "done" or verdict[3] != "completed":
        return None, None, "final_run_not_approved_review"
    handoffs = [tuple(run) for run in runs[:-1] if run[3] == "review_requested"]
    if not handoffs:
        return None, None, "review_handoff_missing"
    handoff = handoffs[-1]
    invalidated = any(
        run[0] > handoff[0] and run[3] == "changes_requested"
        for run in runs[:-1]
    )
    if invalidated:
        return None, None, "review_handoff_invalidated"
    return handoff, verdict, None


def _artifact_actor_error(
    handoff: tuple[Any, ...],
    verdict: tuple[Any, ...],
    expected_sha: str,
    trusted: frozenset[str],
) -> str | None:
    handoff_metadata = _metadata(handoff[5])
    verdict_metadata = _metadata(verdict[5])
    if handoff_metadata.get("commit") != expected_sha:
        return "handoff_sha_mismatch"
    if verdict_metadata.get("reviewed_commit") != expected_sha:
        return "verdict_sha_mismatch"
    named_outcome = verdict_metadata.get("review_outcome")
    if "review_outcome" in verdict_metadata and named_outcome != "approved":
        return "approval_flag_missing"
    if "approved" in verdict_metadata:
        approved = verdict_metadata["approved"] is True
    else:
        approved = named_outcome == "approved"
    if not approved:
        return "approval_flag_missing"
    if handoff[1] == verdict[1]:
        return "reviewer_not_independent"
    return None if verdict[1] in trusted else "reviewer_not_authorized"


def verify_exact_review(
    connection: sqlite3.Connection,
    task_id: str,
    expected_sha: str,
    allowed_reviewers: Collection[str],
) -> dict[str, Any]:
    """Verify the latest immutable run pair approved ``expected_sha``.

    Current task assignment is deliberately ignored. Actor identity comes only
    from immutable ``task_runs.profile`` values, while authorization comes only
    from the caller's already-validated durable delivery policy.
    """
    if not FULL_SHA.fullmatch(expected_sha):
        return {"approved": False, "reason": "expected_sha_not_full"}
    trusted = frozenset(allowed_reviewers)
    if not trusted:
        return {"approved": False, "reason": "reviewer_policy_empty"}
    handoff, verdict, pair_error = _latest_review_pair(connection, task_id)
    if pair_error:
        return {"approved": False, "reason": pair_error}
    assert handoff is not None and verdict is not None
    artifact_error = _artifact_actor_error(handoff, verdict, expected_sha, trusted)
    if artifact_error:
        return {"approved": False, "reason": artifact_error}
    event_error = native_review_event_error(
        connection, task_id, int(handoff[0]), int(verdict[0])
    )
    if event_error:
        return {"approved": False, "reason": event_error}

    return {
        "approved": True,
        "task_id": task_id,
        "reviewed_sha": expected_sha,
        "handoff_run_id": int(handoff[0]),
        "review_run_id": int(verdict[0]),
        "builder_profile": str(handoff[1]),
        "reviewer_profile": str(verdict[1]),
    }
