#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rounds=3

usage() {
  cat <<'EOF'
Usage: scripts/verify-telemetry.sh [--rounds N]

Runs an all-local-bot telemetry battle, audits emitted JSONL files, and checks
the telemetry viewer health endpoint.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rounds)
      if [[ $# -lt 2 || ! "$2" =~ ^[1-9][0-9]*$ ]]; then
        echo "--rounds requires a positive integer." >&2
        exit 1
      fi
      rounds="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cd "$ROOT_DIR"

tmp_output="$(mktemp)"
cleanup() {
  rm -f "$tmp_output"
  if [[ -n "${telemetry_dir:-}" ]]; then
    scripts/telemetry-ui.sh stop --dir "$telemetry_dir" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

scripts/run-battle.sh \
  --telemetry \
  --telemetry-viewer \
  --rounds "$rounds" \
  bots/adaptive-prime \
  bots/chase-lock \
  bots/circle-strafer \
  bots/sweep-pressure \
  2>&1 | tee "$tmp_output"

telemetry_dir="$(sed -n 's/^Telemetry dir: //p' "$tmp_output" | tail -1)"
if [[ -z "$telemetry_dir" || ! -d "$telemetry_dir" ]]; then
  echo "Could not determine telemetry directory from battle output." >&2
  exit 1
fi

tools/telemetry_audit.py "$telemetry_dir" \
  --require-bot adaptive-prime \
  --require-bot chase-lock \
  --require-bot circle-strafer \
  --require-bot sweep-pressure

url_file="$telemetry_dir/telemetry-viewer.url"
if [[ ! -f "$url_file" ]]; then
  echo "Telemetry viewer URL file was not written: $url_file" >&2
  exit 1
fi

viewer_url="$(tr -d '[:space:]' < "$url_file")"
"${PYTHON_BIN:-.venv/bin/python}" - "$viewer_url" <<'PY'
import json
import sys
from urllib.request import urlopen

url = sys.argv[1].rstrip("/") + "/api/health"
with urlopen(url, timeout=5) as response:
    payload = json.loads(response.read().decode("utf-8"))
if not payload.get("ok"):
    raise SystemExit(f"viewer health check failed: {payload}")
print(f"Telemetry viewer health ok: {url}")
PY

echo "Telemetry verified: $telemetry_dir"
