$ErrorActionPreference = 'Stop'

docker compose config --quiet
docker compose -f compose.prod.yaml config --quiet
Write-Host 'Compose files are valid.'
