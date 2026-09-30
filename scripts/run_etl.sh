#!/usr/bin/env bash
# Process every new log file in the incoming directory (run by cron, or manually).
#   success -> moved to $LOGPULSE_PROCESSED_DIR     failure -> moved to $LOGPULSE_FAILED_DIR
# Usage: ./scripts/run_etl.sh [incoming-dir]
# A lock prevents overlapping runs; files modified in the last 10 s are skipped (still being written).
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

INCOMING="$(abs_path "${1:-${LOGPULSE_INCOMING_DIR:-./incoming_logs}}")"
PROCESSED="$(abs_path "${LOGPULSE_PROCESSED_DIR:-./processed_logs}")"
FAILED="$(abs_path "${LOGPULSE_FAILED_DIR:-./failed_logs}")"
LOCK_FILE="${LOGPULSE_LOCK_FILE:-/tmp/logpulse_etl.lock}"
mkdir -p "$INCOMING" "$PROCESSED" "$FAILED"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "Another ETL run is in progress; exiting"
    exit 0
fi

processed=0; failed=0
while IFS= read -r -d '' file; do
    name="$(basename "$file")"
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    log "Processing $name"
    if python manage.py process_logs "$file" --rejects-file "$PROJECT_DIR/rejected/${name}.rejects"; then
        mv "$file" "$PROCESSED/${stamp}_${name}"
        processed=$((processed + 1))
    else
        log "FAILED: $name"
        mv "$file" "$FAILED/${stamp}_${name}"
        failed=$((failed + 1))
    fi
done < <(find "$INCOMING" -maxdepth 1 -type f \( -name '*.log' -o -name '*.jsonl' -o -name '*.json' -o -name '*.gz' \) \
             ! -newermt '10 seconds ago' -print0 | sort -z)

log "ETL finished: $processed processed, $failed failed"
[[ $failed -eq 0 ]]
