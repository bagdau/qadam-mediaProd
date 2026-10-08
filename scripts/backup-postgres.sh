#!/usr/bin/env sh
set -eu

: "${BACKUP_DIR:?Set BACKUP_DIR to an existing backup directory}"
test -d "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose -f compose.prod.yaml exec -T postgres \
  pg_dump -U qadam -d qadam --format=custom > "$BACKUP_DIR/qadam-$stamp.dump"
