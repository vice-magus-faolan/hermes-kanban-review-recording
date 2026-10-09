# Security boundaries

The hook reads the dispatcher-pinned SQLite board read-only and the operator's
version-2 delivery policy. It modifies only metadata passed to the existing
kanban_complete tool; native task/run ownership checks still apply.

Trust assumes the host, dispatcher environment, SQLite history, delivery policy
and installed plugin code are operator-controlled. This is not a sandbox or a
cryptographic attestation against a worker that can edit those trusted inputs.
Use native approval controls and keep the downstream exact-review delivery guard.

Completion is the reviewer's explicit approval action. Reject via the native
kanban_request_changes tool. Contradictory metadata fails closed; report prose
is not parsed. Missing policy and optional/non-Git boards are out of scope.
The plugin cannot attest that a reviewer inspected code or ran tests.

Install a selected immutable commit and enable only in intended reviewer profiles.
Disable the same plugin/profile to roll back; never rewrite historical verdicts.
No network calls, new tools, scheduler or plugin-owned state database are added.

For a suspected vulnerability, do not post live policies, databases, credentials
or exploitable private deployment details in public issues. Use GitHub private
vulnerability reporting if available, or contact the maintainer privately first.
