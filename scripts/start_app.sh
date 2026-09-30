#!/usr/bin/env bash
# Apply migrations and start the web app.
# Usage: ./scripts/start_app.sh [dev|prod] [bind-address]
#   dev  -> Django runserver (default)      prod -> gunicorn
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

MODE="${1:-dev}"
BIND="${2:-0.0.0.0:8000}"

log "Applying migrations"
python manage.py migrate --noinput

case "$MODE" in
    dev)
        log "Starting development server on $BIND"
        exec python manage.py runserver "$BIND"
        ;;
    prod)
        python manage.py collectstatic --noinput
        log "Starting gunicorn on $BIND"
        exec gunicorn config.wsgi:application --bind "$BIND" --workers "${GUNICORN_WORKERS:-3}" --access-logfile -
        ;;
    *)
        echo "Usage: $0 [dev|prod] [bind-address]" >&2
        exit 2
        ;;
esac
