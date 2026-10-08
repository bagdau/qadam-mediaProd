#!/usr/bin/env bash
# Issue/renew a Let's Encrypt certificate (HTTP-01 via the running nginx) and install it for nginx.
# Requires: stack running (compose.prod.yaml), DNS of SERVER_NAME pointing at this host, ports 80/443 reachable.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${SERVER_NAME:?}"; : "${LETSENCRYPT_EMAIL:?set LETSENCRYPT_EMAIL in .env}"
C="docker compose -f compose.prod.yaml --profile tls"

$C run --rm certbot
$C run --rm --entrypoint sh certbot -c \
  "cp -L /etc/letsencrypt/live/$SERVER_NAME/fullchain.pem /out/fullchain.pem && \
   cp -L /etc/letsencrypt/live/$SERVER_NAME/privkey.pem /out/privkey.pem && chmod 644 /out/*.pem"
docker compose -f compose.prod.yaml exec -T nginx nginx -s reload
echo "certificate for $SERVER_NAME installed and nginx reloaded"
