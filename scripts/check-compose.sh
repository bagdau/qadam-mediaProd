#!/usr/bin/env sh
set -eu

docker compose config --quiet
docker compose -f compose.prod.yaml config --quiet
echo 'Compose files are valid.'
