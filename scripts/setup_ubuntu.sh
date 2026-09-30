#!/usr/bin/env bash
# One-time setup on Ubuntu 22.04/24.04: installs PostgreSQL, creates the DB role + database,
# creates a virtualenv, installs dependencies and runs migrations.
# Usage: ./scripts/setup_ubuntu.sh
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

[[ -f .env ]] || cp .env.example .env
set -a; source .env; set +a
DB_NAME="${POSTGRES_DB:-logpulse}"; DB_USER="${POSTGRES_USER:-logpulse}"; DB_PASSWORD="${POSTGRES_PASSWORD:-logpulse}"

echo ">> Installing system packages (needs sudo)"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip postgresql postgresql-contrib
sudo systemctl enable --now postgresql

echo ">> Creating PostgreSQL role '${DB_USER}' and database '${DB_NAME}'"
# CREATEDB lets Django's test runner create its temporary test database.
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}' CREATEDB;
    END IF;
END
\$\$;
SQL
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
    || sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"

echo ">> Creating virtualenv and installing dependencies"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ">> Running migrations"
python manage.py migrate
chmod +x scripts/*.sh
echo "Done. Start the app with: ./scripts/start_app.sh"
