#!/usr/bin/env bash
# r2_sync.sh — uploads a local directory to Cloudflare R2 (plan §3, §5.2). Idempotent.
#
#   R2_ACCOUNT_ID=… R2_ACCESS_KEY_ID=… R2_SECRET_ACCESS_KEY=… \
#     scripts/r2_sync.sh build/assets pi-alpha-assets [prefix] [rclone flags, e.g. --dry-run]
#   R2_REMOTE=/tmp/fake/ scripts/r2_sync.sh …   # local target, no credentials (tests)
#
# Uses `rclone copy`, NOT `sync`: the CI token has no delete permission (plan §9 — bucket without delete for CI),
# and an accidentally empty source would otherwise wipe the archive. Deletion = manual, outside CI.
# rclone config only via env (no ~/.config/rclone/rclone.conf in the runner).
set -euo pipefail

src=${1:?zdrojový adresář}
bucket=${2:?název bucketu}
shift 2
prefix=
if [[ $# -gt 0 && $1 != -* ]]; then prefix=$1; shift; fi   # optional prefix; the rest = rclone flags
extra=("$@")

# R2_REMOTE overrides the target (tests: a local directory); default is the env-configured R2 remote
remote=${R2_REMOTE:-r2:}
if [[ $remote == r2: ]]; then
  : "${R2_ACCOUNT_ID:?chybí R2_ACCOUNT_ID}" "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}"
  export RCLONE_CONFIG_R2_TYPE=s3
  export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
  export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
  export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
  export RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
  export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true   # per-bucket token cannot list buckets
fi
dst="${remote}${bucket}/${prefix}"

# Cache by type: *.wNNN.webp variants are derived and unchanging → immutable;
# *.json indexes change → 5 min; everything else (originals the client may overwrite) → 1 day.
up() { rclone copy "$src" "$dst" --transfers 16 --checkers 32 --fast-list \
         --stats-one-line --stats 30s "$@"; }
up --include '*.w[0-9]*.webp' --header-upload 'Cache-Control: public, max-age=31536000, immutable' ${extra[@]+"${extra[@]}"}
up --include '*.json'         --header-upload 'Cache-Control: public, max-age=300' ${extra[@]+"${extra[@]}"}
up --exclude '*.w[0-9]*.webp' --exclude '*.json' --header-upload 'Cache-Control: public, max-age=86400' ${extra[@]+"${extra[@]}"}
