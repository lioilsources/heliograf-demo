#!/usr/bin/env bash
# build_site.sh — one build for every target: GitHub Pages (deploy.yml), Lighthouse (lighthouse.yml),
# backup Cloudflare Pages (deploy-cloudflare.yml) and the local demo. Plan §5.2, plan 01 block D5.
#
#   DOMAIN=pi-alpha.org ASSETS_URL=https://assets.pi-alpha.org MOBILE=1 [PWA=1] [PREVIEW=0] scripts/build_site.sh [OUT=_site]
#
# site/ is never modified; everything happens in OUT. MOBILE=0 = 1:1 migration without the mobile layer.
# raw/ holds signed originals and is copied byte-exact (no link rewrite, no mobile layer).
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-_site}
py=${PYTHON:-python3}
mobile=${MOBILE:-1}

case $(cd "$(dirname "$out")" 2>/dev/null && pwd)/$(basename "$out") in
  /|"$root"|"$root/site"|"$root/site/"*) echo "refusing to build into $out" >&2; exit 1 ;;
esac
rm -rf -- "${out:?}"
cp -R "$root/site" "$out"
mkdir -p "$out/shared"
cp -R "$root/shared/." "$out/shared/"
touch "$out/.nojekyll"
if [[ -f $root/CNAME ]]; then cp "$root/CNAME" "$out/"; fi

if [[ -f $root/data/assets-map.json ]]; then
  "$py" "$root/scripts/rewrite_links.py" "$out" --map "$root/data/assets-map.json" \
    --domain "${DOMAIN:?DOMAIN is required with assets-map.json}" --exclude 'raw/*' --apply
fi
pwa_args=()
if [[ $mobile != 0 && ${PWA:-1} != 0 && -f $root/data/pwa.json ]]; then pwa_args=(--pwa-config "$root/data/pwa.json"); fi
if [[ $mobile != 0 ]]; then
  "$py" "$root/scripts/mobilize.py" "$out" --css /shared/mobile.css --assets "${ASSETS_URL:-}" \
    --variants "$root/data/variants.json" --blacklist-file "$root/data/srcset-blacklist.txt" \
    --file-sizes "$root/data/asset-sizes.json" \
    --exclude 'raw/*' ${pwa_args[@]+"${pwa_args[@]}"} --apply
fi
# PWA (plan 02 A): with data/pwa.json, MOBILE=1 and PWA≠0; otherwise a self-unregistering sw.js (kill switch)
if [[ -f $root/data/pwa.json ]]; then
  if (( ${#pwa_args[@]} )); then
    "$py" "$root/scripts/pwa.py" "$out" --config "$root/data/pwa.json" --icons "$root/data/icons" \
      --assets "${ASSETS_URL:-}" --build-id "${BUILD_ID:-${GITHUB_SHA:-}}"
  else
    "$py" "$root/scripts/pwa.py" "$out" --kill
  fi
fi
# PREVIEW=1: site under a subpath (user.github.io/<repo>/) → relative links + noindex
if [[ ${PREVIEW:-0} != 0 ]]; then
  "$py" "$root/scripts/relativize.py" "$out" --noindex --exclude 'raw/*'
  rm -f "$out/CNAME"
fi
echo "build: $out ($(find "$out" -type f | wc -l | tr -d ' ') souborů, MOBILE=$mobile)"
