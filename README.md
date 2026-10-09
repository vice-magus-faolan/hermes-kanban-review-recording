# Hermes Kanban Review Recording

A dependency-free native Hermes plugin that records approval bookkeeping before
an authorized independent reviewer completes a native review. It changes no
Hermes core code and adds no model-facing tools or report-format requirements.

**Status:** extracted implementation for review. Publication is not live activation.
Plugin ID: `kanban-review-recording`. Repository: `hermes-kanban-review-recording`.

## Decision versus recording

In the native same-card lifecycle, the reviewer chooses `kanban_complete` to
approve, or `kanban_request_changes` to reject. This plugin uses that explicit
tool action, **not keywords in the report**, as the decision. For an active
review-phase completion on a Git board with required review, it derives the
candidate SHA from the latest valid builder handoff and supplies:

- `approved: true`
- `review_outcome: approved`
- `reviewed_commit: <the builder's exact full SHA>`

It preserves the report, artifacts and unrelated metadata. Explicit negative
approval, a mismatched SHA, blocking findings, unauthorized/self-review, invalid
handoffs or policy failures are refused **before** native completion. Ordinary
builder completions, other tools and boards without required Git review remain
unchanged. Native task/run ownership checks still execute. The separate
downstream exact-review delivery guard remains independent and unchanged.

The plugin reads the native database and policy only. It neither closes tasks
itself nor rewrites historical runs. It cannot certify test execution, satisfy
unexecuted acceptance criteria or authorize publication/deployment.

## Policy and worker context

The dispatcher supplies `HERMES_KANBAN_TASK`, `HERMES_KANBAN_RUN_ID`,
`HERMES_KANBAN_BOARD` and `HERMES_KANBAN_DB`. An optional `HERMES_KANBAN_HOME`
must match the database's shared home. Named boards use
`<shared-home>/kanban/boards/<board>/kanban.db`; the native default board uses
`<shared-home>/kanban.db`. Policy is read from
`<shared-home>/kanban/delivery-policy.json`, not the reviewer's profile home.

The version-2 policy is an operator control-plane contract, **not built-in
Hermes policy**. This plugin consumes an existing policy; it does not install or
own the delivery guard. A minimal illustration of the consumed fields is:

```json
{
  "policy_version": 2,
  "boards": {
    "example": {
      "mode": "git",
      "review": {"required": true, "allowed_profiles": ["independent-reviewer"]}
    }
  }
}
```

This is not a full delivery-policy template. Preserve the rest of an existing
policy and use its owner's validation tooling. No policy means no modification;
optional/non-Git/unlisted boards pass through. Malformed policy/context can block
a completion before scope is fully determined; repair trusted configuration,
never loosen it just to complete a task.

## Installation and rollback

Use only an explicitly reviewed immutable commit and the intended reviewer
profile. The runtime bundle is at repository root (`plugin.yaml`, `__init__.py`).
Native Git installation, **after separate deployment approval**:

```sh
hermes -p <reviewer> plugins install vice-magus-faolan/hermes-kanban-review-recording --ref <full-reviewed-commit-sha> --no-enable
hermes -p <reviewer> plugins doctor kanban-review-recording --ci
hermes -p <reviewer> plugins enable kanban-review-recording --no-allow-tool-override
```

Alternatively, copy only the two runtime files from the selected clean commit
into `<profile-home>/plugins/kanban-review-recording/`, record the source SHA and
verify copied hashes, then doctor/enable using the same native profile controls.
Do not link a live plugin to a writable feature worktree.

There is no built-in tool override or extra runtime dependency. Already-running
workers are not retroactively patched. Verify activation through the intended
profile's fresh process. Roll back with:

```sh
hermes -p <reviewer> plugins disable kanban-review-recording
```

Do not restart unrelated services or widen review policy as part of activation.
For an existing approval with incomplete recording, preserve the closed run.
A fresh, bounded native reviewer confirmation may reaffirm the same artifact;
the plugin never manufactures that confirmation itself.

## Reproducible verification

The exercised baseline is Python 3.14/Linux and clean NousResearch/hermes-agent
commit `f42f579cf8bac4918ac9599bece71618afadd846`. The test dependencies below are
only for an isolated test environment, not plugin dependencies or permission to
pip-edit a live Hermes generation.

From this repository:

```sh
git clone https://github.com/NousResearch/hermes-agent.git .hermes-runtime-source
git -C .hermes-runtime-source checkout --detach f42f579cf8bac4918ac9599bece71618afadd846
python3 -m venv .venv-test
.venv-test/bin/python -m pip install -r requirements-test.txt
export HERMES_AGENT_ROOT="$PWD/.hermes-runtime-source"
.venv-test/bin/python scripts/verify.py
```

The same canonical command is `python3 scripts/verify.py` when the interpreter
already has the declared test dependencies. It refuses missing/wrong/dirty core
source, test failures and skips, and runs native Plugin Doctor. CI checks out
that exact core commit into an isolated checkout and runs this command.

Tests use disposable homes/databases. The native integration runs real
create/claim/request-review/reviewer-claim APIs, native hook merging and the
model-facing `kanban_complete` handler. The frozen test-only external guard
oracle preserves the original consumer checks without importing the workspace.
Without the hook, genuine completion reproduces the missing-approval rejection;
with it, ordinary prose produces a valid exact-SHA approval record. Conflicting
approval and wrong-SHA calls leave the run open. Other tests cover authorization,
handoff provenance, metadata preservation, pass-through and idempotence.
These tests and Doctor do not prove live installation, human review or production
acceptance. See [provenance](docs/provenance.md), [security](SECURITY.md) and
[contributing](CONTRIBUTING.md).

## License

SPDX-License-Identifier: **GPL-3.0-or-later**. See [LICENSE](LICENSE).
