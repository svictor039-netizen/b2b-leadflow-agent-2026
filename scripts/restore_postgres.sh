#!/usr/bin/env bash
# Restore PostgreSQL backup ONLY into an explicitly named non-production database.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: restore_postgres.sh --target-db <database_name> --i-understand yes <backup.dump>

Safety:
  - Refuses to restore into the production database parsed from DATABASE_URL.
  - Requires --i-understand yes to proceed.
  - Target database name must match ^[a-zA-Z_][a-zA-Z0-9_]*$
EOF
}

TARGET_DB=""
CONFIRM=""
BACKUP_FILE=""
POSTGRES_USER="${POSTGRES_USER:-leadflow}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml}"

if [[ -n "${DATABASE_URL:-}" ]]; then
  PRODUCTION_DB="$(python3 - <<'PY'
import os
from urllib.parse import urlparse
parsed = urlparse(os.environ["DATABASE_URL"])
print((parsed.path or "/").lstrip("/") or "leadflow")
PY
)"
else
  PRODUCTION_DB="${POSTGRES_DB:-leadflow}"
fi

is_safe_identifier() {
  [[ "$1" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-db) TARGET_DB="$2"; shift 2 ;;
    --i-understand) CONFIRM="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) BACKUP_FILE="$1"; shift ;;
  esac
done

if [[ -z "$TARGET_DB" || -z "$CONFIRM" || -z "$BACKUP_FILE" ]]; then
  usage
  exit 1
fi

if [[ "$CONFIRM" != "yes" ]]; then
  echo "ERROR: pass --i-understand yes to confirm restore into test database." >&2
  exit 1
fi

if ! is_safe_identifier "$TARGET_DB"; then
  echo "ERROR: target database name contains invalid characters." >&2
  exit 1
fi

if [[ "$TARGET_DB" == "$PRODUCTION_DB" ]]; then
  echo "ERROR: refusing to restore into production database '$PRODUCTION_DB'." >&2
  exit 1
fi

if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file missing or empty: $BACKUP_FILE" >&2
  exit 1
fi

echo "Creating target database '$TARGET_DB' if needed..."
docker compose $COMPOSE_FILES exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${TARGET_DB}';
DROP DATABASE IF EXISTS "${TARGET_DB}";
CREATE DATABASE "${TARGET_DB}";
SQL

echo "Restoring backup into '$TARGET_DB'..."
docker compose $COMPOSE_FILES exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$TARGET_DB" --no-owner --role="$POSTGRES_USER" < "$BACKUP_FILE"

echo "Restore OK — target database: $TARGET_DB"
