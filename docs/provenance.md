# Extraction provenance and compatibility

This repository extracts the five-file kanban-review-recording bundle from the
review-recording workspace change at commit
`744650a3bfbfc2f82c61cf956b163a87b8198254`. No workspace Git history, live config,
board databases, policies, credentials or unrelated scripts are imported.

The initial runtime `__init__.py` and plugin.yaml are byte-for-byte unchanged.
Initial __init__.py SHA-256:
`e0460c48718d51efa2f3ef6c5b18f25ad1805fcf491e62feb0c37dfcbe9f16ef`.
README and tests are adapted for the standalone repository; licensing, CI,
verification, contributor and security guidance are added.

## Frozen downstream consumer oracle

`tests/fixtures/exact_review_guard.py` contains these pure functions copied
without function-body changes from the original separate delivery guard:
`_metadata`, `native_review_event_error`, `_latest_review_pair`,
`_artifact_actor_error`, `verify_exact_review`.

Original source Git blob: `003b438d657dd11534d420ed9d39312e49935147`.
Original whole-file SHA-256:
`69ad7e825c8b12b5a87c20ccea1e049b5b908e85516c2a3e1e648b42f543e925`.
Workspace/path resolution, policy loading and the guard CLI are intentionally
excluded. This frozen test oracle adds no runtime dependency or delivery power.
The initial extraction compares all five function ASTs to the source blob.

Native integration and Plugin Doctor target clean NousResearch/hermes-agent
commit `f42f579cf8bac4918ac9599bece71618afadd846` on Python 3.14/Linux.
This is the exercised compatibility baseline, not a claim about all Hermes
versions. It relies on that version's native review run/event schema and
pre_tool_call modify/argument-merge behavior. The version-2 delivery policy is
an operator control-plane contract, not a policy supplied by Hermes core.
