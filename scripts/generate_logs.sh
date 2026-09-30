#!/usr/bin/env bash
# Generate synthetic logs. Usage: ./scripts/generate_logs.sh [count] [output-file] [extra generate_logs args...]
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

COUNT="${1:-10000}"
OUTPUT="${2:-sample_logs/generated.log}"
shift $(( $# > 2 ? 2 : $# ))

log "Generating $COUNT log lines into $OUTPUT"
python manage.py generate_logs --count "$COUNT" --output "$OUTPUT" "$@"
log "Done: $(wc -l < "$OUTPUT") lines, $(du -h "$OUTPUT" | cut -f1)"
