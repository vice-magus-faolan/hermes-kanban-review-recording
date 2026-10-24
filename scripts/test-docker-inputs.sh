#!/usr/bin/env bash
# Exercise the real mount boundary; never use real credentials or databases.
set -euo pipefail
mkdir -p .docker-input
canaries=$(mktemp -d .docker-input/docker-privacy.XXXXXX)
new_test=''
cleanup() {
    result=$?
    trap - EXIT INT TERM
    cleanup_status=0
    if [[ -n $new_test ]]; then rm -f -- "$new_test" || cleanup_status=1; fi
    rm -rf -- "$canaries" || cleanup_status=1
    if [[ -e $canaries || ( -n $new_test && -e $new_test ) ]]; then cleanup_status=1; fi
    printf 'Privacy fixture cleanup=%s\n' "$cleanup_status"
    if [[ $result -ne 0 ]]; then exit "$result"; fi
    exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'FAKE test credential; no private data\n' > "$canaries/credentials.env"
printf 'FAKE test database; no private data\n' > "$canaries/state.db"
chmod 755 "$canaries"
chmod 644 "$canaries/credentials.env" "$canaries/state.db"
git check-ignore -q -- "$canaries/credentials.env"
git check-ignore -q -- "$canaries/state.db"
# A normal new source/test file must be available without first staging it in Git.
new_test=$(mktemp tests/docker-privacy-input.XXXXXX.py)
printf '# Disposable source-discovery canary.\n' > "$new_test"
chmod 644 "$new_test"
mkdir "$canaries/staging"
scratch=$(cd "$canaries/staging" && pwd -P)
for expected in 0 37; do
    if TMPDIR="$scratch" bash scripts/verify-docker.sh bash -c '
        set -eu
        for input in __init__.py plugin.yaml scripts/verify.py tests/test_native_completion.py tests/fixtures/exact_review_guard.py "$2"; do
            test -r "$input" || { printf "Required input unavailable: %s\n" "$input" >&2; exit 1; }
        done
        privacy=0
        for private in "$1/credentials.env" "$1/state.db" .git .docker-input; do
            if test -e "$private"; then
                printf "Private checkout input exposed inside /source: %s\n" "$private" >&2
                privacy=1
            fi
        done
        if test "$privacy" -ne 0; then exit 1; fi
        exit "$3"
    ' privacy-check "$canaries" "$new_test" "$expected"; then
        actual=0
    else
        actual=$?
    fi
    if [[ $actual -ne $expected ]]; then
        printf 'Privacy invocation returned %s; expected %s\n' "$actual" "$expected" >&2
        exit 1
    fi
    shopt -s nullglob dotglob
    remaining=("$scratch"/*)
    if [[ ${#remaining[@]} -ne 0 ]]; then
        printf 'Owned source staging remains after exit %s\n' "$expected" >&2
        exit 1
    fi
done
printf 'VERIFIED: Docker excludes ignored inputs; new test readable; exit37 preserved; staging removed.\n'
