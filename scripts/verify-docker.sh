#!/usr/bin/env bash
# Run from the plugin snapshot root. The image contains only test prerequisites.
set -euo pipefail
image=${REVIEW_TEST_IMAGE:-hermes-kanban-review-recording:test}
run="review-recording-$(date +%s%N)-$$"
label="org.hermes-kanban-review-recording.run=$run"
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
    printf 'Test exit=%s; owned resource cleanup=%s; run=%s\n' "$result" "$cleanup_status" "$run"
    if [[ $result -ne 0 ]]; then exit "$result"; fi
    exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ $# -eq 0 ]]; then set -- python3 scripts/verify.py; fi
docker run --rm --name "$run" --label "$label" --network none \
    --read-only --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges \
    --cpus 2 --memory 2g --pids-limit 256 \
    --tmpfs /scratch:rw,nosuid,nodev,size=512m,mode=1777 \
    --mount "type=bind,src=$PWD,dst=/source,readonly" "$image" "$@"
