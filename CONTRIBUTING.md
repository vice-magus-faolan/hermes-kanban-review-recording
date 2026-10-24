# Contributing

Use the clean pinned Hermes source and Docker build documented in
README.md, then run:

```sh
bash scripts/verify-docker.sh
bash scripts/test-docker-inputs.sh
bash scripts/verify-docker.sh ruff check --no-cache --isolated --select C901 --config 'lint.mccabe.max-complexity = 10' __init__.py scripts/verify.py
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

All tests, native Doctor and lint run in the disposable container, not a host
virtualenv. Source-only build inputs must retain real clean Git identity. The
wrapper selects root runtime files and Python/shell inputs under scripts/tests
from the Git working tree, including new nonignored tests. Run it at the Git
repository root with Bash, Git and GNU coreutils available; a source archive
alone is not supported. Ignored files, Git metadata and unrelated root files
are never mounted. Links, missing required inputs and unsupported fixture
formats are refused; add any genuinely needed format to the deliberate input
set rather than broadening the mount. The owned readable snapshot is removed
on success and failure. The Docker privacy regression checks harmless ignored
canaries, new-file discovery, failure propagation and cleanup in CI. Do not
mount live state to debug a test.
