#!/usr/bin/env bash
# Container entrypoint: migrate, collect static files, optionally seed demo data, start gunicorn.
set -euo pipefail

python manage.py migrate --noinput
python manage.py collectstatic --noinput
if [[ "${LOGPULSE_SEED_DEMO:-1}" == "1" ]]; then
    python manage.py seed_demo --count "${LOGPULSE_DEMO_COUNT:-10000}"
fi
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" --access-logfile -
