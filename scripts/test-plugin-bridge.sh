#!/usr/bin/env bash
# Smoke test for the plugin bridge.
# Assumes the broker is running on localhost:8765 with a real plugins cache.
set -euo pipefail

PORT="${PORT:-8765}"
BASE="http://localhost:${PORT}"

echo "[1] GET /api/plugins"
body=$(curl -sf "${BASE}/api/plugins")
echo "$body" | python3 -c "
import json, sys
data = json.load(sys.stdin)
plugs = data.get('plugins') or []
assert plugs, 'no plugins returned (broker may not see ~/.claude/plugins/cache/)'
print(f'   {len(plugs)} plugins discovered:')
for p in plugs[:5]:
    print(f'     - {p[\"id\"]} v{p[\"version\"]} '
          f'(skills={p[\"skills\"]}, agents={p[\"agents\"]}, commands={p[\"commands\"]})')
"

# Pick the first plugin and fetch its detail
first=$(echo "$body" | python3 -c "import json,sys;print(json.load(sys.stdin)['plugins'][0]['id'])")
echo "[2] GET /api/plugins/${first}"
curl -sf "${BASE}/api/plugins/${first}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('id') == '${first}'
assert d.get('path')
print(f'   path = {d[\"path\"]}')
print(f'   manifest keys = {sorted((d.get(\"manifest\") or {}).keys())}')
"

echo "[3] GET /api/plugins/__nonexistent__ (expect 404)"
status=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/api/plugins/__nonexistent__")
test "$status" = "404" || { echo "expected 404 got $status"; exit 1; }
echo "   ok"

echo "All plugin-bridge smoke checks passed."
