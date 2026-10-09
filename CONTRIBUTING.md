# Contributing

Use the clean pinned Hermes source and isolated test prerequisites documented in
README.md, then run:

```sh
python3 scripts/verify.py
```

Keep tests network-free and production-state-free. The native lifecycle tests
must exercise actual create, claim, request-review, reviewer-claim, hook dispatch
and completion APIs, not just synthetic tables. Retain the no-hook negative case.
Do not change the frozen consumer oracle to make altered producer output pass.
Changing compatibility requires an explicit source pin/provenance update and
review against the real external consumer, not silently accepting any version.

Keep pull requests focused, document risks and verification, and do not claim
live install/activation from unit tests or Plugin Doctor. Runtime rollout is a
separately authorized operation.
