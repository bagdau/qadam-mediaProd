#!/usr/bin/env bash
# Self-signed certificate for LOCAL testing of compose.prod.yaml. Use Let's Encrypt (README) in production.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-localhost}"
OUT=infrastructure/nginx/certs
mkdir -p "$OUT"
MSYS_NO_PATHCONV=1 openssl req -x509 -nodes -newkey rsa:2048 -days 30 -keyout "$OUT/privkey.pem" -out "$OUT/fullchain.pem" \
  -subj "/CN=$NAME" -addext "subjectAltName=DNS:$NAME,DNS:localhost,IP:127.0.0.1"
chmod 644 "$OUT/fullchain.pem" "$OUT/privkey.pem"
echo "wrote $OUT/fullchain.pem and $OUT/privkey.pem for $NAME (valid 30 days, NOT trusted by browsers)"
