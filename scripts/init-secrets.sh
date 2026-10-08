#!/usr/bin/env bash
# Generates ./secrets/* for compose.prod.yaml. Existing files are never overwritten.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p secrets
umask 077

rand() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c "${1:-40}"; }
fernet() { python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())' 2>/dev/null \
           || head -c 32 /dev/urandom | base64 | tr '+/' '-_' ; }

make() { # name generator...
  local name="$1"; shift
  if [ -s "secrets/$name" ]; then echo "keep   secrets/$name"; else "$@" > "secrets/$name"; echo "create secrets/$name"; fi
}

make postgres_password   rand 40
make redis_password      rand 40
make secret_key          rand 64
make encryption_keys     fernet
[ -e secrets/tiktok_client_secret ] || { : > secrets/tiktok_client_secret; echo "create secrets/tiktok_client_secret (EMPTY - paste your TikTok client secret into it)"; }
[ -e secrets/bootstrap_admin_password ] || { rand 24 > secrets/bootstrap_admin_password; echo "create secrets/bootstrap_admin_password"; }
chmod 600 secrets/* 2>/dev/null || true
echo
echo "Next: put the TikTok client secret into secrets/tiktok_client_secret (no trailing spaces)."
echo "Back up secrets/encryption_keys: without it stored TikTok tokens cannot be decrypted."
