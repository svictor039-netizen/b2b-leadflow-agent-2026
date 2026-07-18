#!/usr/bin/env bash
# Create a timestamped PostgreSQL backup via Docker Compose postgres service.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
POSTGRES_USER="${POSTGRES_USER:-leadflow}"
POSTGRES_DB="${POSTGRES_DB:-leadflow}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml}"
BACKUP_FILE="$BACKUP_DIR/leadflow_${POSTGRES_DB}_${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

echo "Creating backup: $BACKUP_FILE"
docker compose $COMPOSE_FILES exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$BACKUP_FILE"

if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file is missing or empty: $BACKUP_FILE" >&2
  exit 1
fi

BYTES="$(wc -c < "$BACKUP_FILE" | tr -d ' ')"
echo "Backup OK — ${BYTES} bytes — $BACKUP_FILE"
