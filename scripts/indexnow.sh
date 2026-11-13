#!/usr/bin/env bash
# Ping IndexNow (Bing, Yandex, and anyone that subscribes — IndexNow is a shared feed).
# Run after publishing changes. Reads URLs from sitemap.xml.
set -euo pipefail

HOST="raigada-garcia.dev"
KEY="c7807bcaa97f4ed417df5cf26cd00b0c"
KEY_LOCATION="https://${HOST}/${KEY}.txt"
SITEMAP_PATH="${1:-sitemap.xml}"

if [[ ! -f "$SITEMAP_PATH" ]]; then
  echo "sitemap not found at $SITEMAP_PATH" >&2
  exit 1
fi

urls=$(grep -oE "<loc>[^<]+</loc>" "$SITEMAP_PATH" | sed -E 's|</?loc>||g')
if [[ -z "$urls" ]]; then
  echo "no URLs in sitemap" >&2
  exit 1
fi

json_urls=$(echo "$urls" | awk 'BEGIN{p=""} {printf "%s\"%s\"", p, $0; p=","}')
payload=$(printf '{"host":"%s","key":"%s","keyLocation":"%s","urlList":[%s]}' \
  "$HOST" "$KEY" "$KEY_LOCATION" "$json_urls")

echo "Posting $(echo "$urls" | wc -l | tr -d ' ') URLs to IndexNow..."
curl -sS -X POST \
  -H "Content-Type: application/json; charset=utf-8" \
  -d "$payload" \
  "https://api.indexnow.org/IndexNow" | tee /dev/stderr
echo
