#!/usr/bin/env bash
# Back up the PostgreSQL database with pg_dump (gzip-compressed) and prune old backups.
# Usage: ./scripts/backup_db.sh        Restore: gunzip -c backups/<file>.sql.gz | psql -h HOST -U USER DBNAME
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

BACKUP_DIR="$(abs_path "${LOGPULSE_BACKUP_DIR:-./backups}")"
RETENTION_DAYS="${LOGPULSE_BACKUP_RETENTION_DAYS:-7}"
DB_NAME="${POSTGRES_DB:-logpulse}"
mkdir -p "$BACKUP_DIR"

target="$BACKUP_DIR/${DB_NAME}_$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
tmp="${target}.partial"
trap 'rm -f "$tmp"' ERR

log "Backing up '$DB_NAME' to $target"
PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
    --host "${POSTGRES_HOST:-localhost}" --port "${POSTGRES_PORT:-5432}" \
    --username "${POSTGRES_USER:-logpulse}" --no-owner --dbname "$DB_NAME" | gzip -9 > "$tmp"
mv "$tmp" "$target"

log "Backup complete ($(du -h "$target" | cut -f1)); removing backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -print -delete
