#!/usr/bin/env bash
# Run from the plugin Git root. The image contains only test prerequisites.
set -euo pipefail
image=${REVIEW_TEST_IMAGE:-hermes-kanban-review-recording:test}
run="review-recording-$(date +%s%N)-$$"
label="org.hermes-kanban-review-recording.run=$run"
staging=''
cleanup() {
    result=$?
    trap - EXIT INT TERM
    cleanup_status=0
    docker rm -f "$run" >/dev/null 2>&1 || {
        # --rm normally already removed it; query success is still mandatory.
        remaining=$(docker ps -aq --filter "name=^/${run}$") || cleanup_status=1
        if [[ -n ${remaining:-} ]]; then cleanup_status=1; fi
    }
    for resource in container volume network; do
        case $resource in
            container) remaining=$(docker ps -aq --filter "label=$label") || cleanup_status=1 ;;
            volume) remaining=$(docker volume ls -q --filter "label=$label") || cleanup_status=1 ;;
            network) remaining=$(docker network ls -q --filter "label=$label") || cleanup_status=1 ;;
        esac
        if [[ -n ${remaining:-} ]]; then cleanup_status=1; fi
    done
    staging_status=0
    if [[ -n $staging ]]; then
        rm -rf -- "$staging" || staging_status=1
        if [[ -e $staging ]]; then staging_status=1; fi
    fi
    printf 'Test exit=%s; owned resource cleanup=%s; source staging cleanup=%s; run=%s\n' "$result" "$cleanup_status" "$staging_status" "$run"
    if [[ $result -ne 0 ]]; then exit "$result"; fi
    if [[ $staging_status -ne 0 ]]; then exit "$staging_status"; fi
    exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Git selection respects new nonignored tests without disclosing arbitrary cwd
# contents. Keep the list outside the mounted snapshot and reject links rather
# than following them into private files outside the deliberate input boundary.
root=$(pwd -P)
if [[ $(git rev-parse --show-toplevel) != "$root" ]]; then
    printf 'Run verification from the plugin Git root.\n' >&2
    exit 2
fi
staging=$(mktemp -d "${TMPDIR:-/tmp}/review-recording-source.XXXXXX")
mkdir "$staging/source"
git ls-files --cached --others --exclude-standard --deduplicate -z -- \
    __init__.py plugin.yaml scripts tests > "$staging/inputs"
while IFS= read -r -d '' input; do
    # Also exclude tracked files now covered by ignore rules.
    if git check-ignore --no-index -q -- "$input"; then continue; else ignored=$?; fi
    if [[ $ignored -ne 1 ]]; then exit "$ignored"; fi
    case $input in
        __init__.py|plugin.yaml|scripts/*.py|scripts/*.sh|tests/*.py) ;;
        *) printf 'Unsupported verification input: %s\n' "$input" >&2; exit 2 ;;
    esac
    if [[ ! -f $input || -L $input || $(realpath -e -- "$input") != "$root/$input" ]]; then
        printf 'Missing, linked or nonregular verification input: %s\n' "$input" >&2
        exit 2
    fi
    mkdir -p -- "$staging/source/$(dirname -- "$input")"
    cp -- "$input" "$staging/source/$input"
    chmod 644 "$staging/source/$input"
done < "$staging/inputs"
for required in __init__.py plugin.yaml scripts/verify.py; do
    if [[ ! -f $staging/source/$required ]]; then
        printf 'Missing required verification input: %s\n' "$required" >&2
        exit 2
    fi
done
if [[ ! -d $staging/source/tests ]]; then
    printf 'Missing required verification tests.\n' >&2
    exit 2
fi
chmod -R a+rX "$staging"
if [[ $# -eq 0 ]]; then set -- python3 scripts/verify.py; fi
docker run --rm --name "$run" --label "$label" --network none \
    --read-only --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges \
    --cpus 2 --memory 2g --pids-limit 256 \
    --tmpfs /scratch:rw,nosuid,nodev,size=512m,mode=1777 \
    --mount "type=bind,src=$staging/source,dst=/source,readonly" "$image" "$@"
