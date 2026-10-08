#!/usr/bin/env sh
set -eu

dump_path="${1:?Usage: restore-postgres.sh PATH_TO_DUMP}"
test -f "$dump_path"
docker compose -f compose.prod.yaml exec -T postgres \
  pg_restore -U qadam -d qadam --clean --if-exists < "$dump_path"
