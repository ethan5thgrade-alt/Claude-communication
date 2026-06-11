#!/usr/bin/env bash
# Smoke test for the Agent Mesh broker.
#
# Spins the broker up on a dedicated test port pair (18998/18999), waits for
# the HTTP surface to come online, then hits every REST endpoint and checks
# the responses. Exits 0 on success, non-zero otherwise. Always tries to
# clean up the broker process.
set -euo pipefail

UI_PORT=18998
INSTANCE_PORT=18999
BASE="http://localhost:${UI_PORT}"

# Resolve repo root from the script location so this works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default to whichever python first satisfies the broker's imports. CI sets
# PYTHON_BIN=python (since setup-python pins one version); local runs can
# override to e.g. python3.13.
PYTHON_BIN="${PYTHON_BIN:-python3}"
STATE_DIR="$(mktemp -d)"
LOG_FILE="$(mktemp)"
BROKER_PID=""

cleanup() {
  local code=$?
  # Kill the whole process group so the python child dies too (the subshell
  # we spawn doesn't forward signals to its python grandchild on its own).
  if [[ -n "${BROKER_PID}" ]]; then
    if kill -0 "${BROKER_PID}" 2>/dev/null; then
      # Try the process group first, then the PID, then SIGKILL.
      kill -- -"${BROKER_PID}" 2>/dev/null || kill "${BROKER_PID}" 2>/dev/null || true
      sleep 0.2
      if kill -0 "${BROKER_PID}" 2>/dev/null; then
        kill -9 "${BROKER_PID}" 2>/dev/null || true
      fi
      wait "${BROKER_PID}" 2>/dev/null || true
    fi
    # Belt-and-suspenders: hunt any python child still holding our test ports.
    for p in $(lsof -nP -iTCP:${UI_PORT} -sTCP:LISTEN -t 2>/dev/null; \
               lsof -nP -iTCP:${INSTANCE_PORT} -sTCP:LISTEN -t 2>/dev/null); do
      kill -9 "$p" 2>/dev/null || true
    done
  fi
  if [[ ${code} -ne 0 ]]; then
    echo "--- broker log (${LOG_FILE}) ---" >&2
    tail -n 80 "${LOG_FILE}" >&2 || true
  fi
  rm -rf "${STATE_DIR}" "${LOG_FILE}" 2>/dev/null || true
  # Ensure the captured exit code is what the script returns.
  trap - EXIT
  exit "${code}"
}
trap cleanup EXIT INT TERM

echo "[smoke] starting broker on ${UI_PORT}/${INSTANCE_PORT} (state=${STATE_DIR})"

# Tiny launcher: imports the Broker class with overridden ports + state path.
# We exec into python directly inside the subshell so signal-on-cleanup
# reaches the actual broker process (no shell middleman to swallow signals).
(
  cd "${REPO_ROOT}"
  exec "${PYTHON_BIN}" -u -c "
import asyncio, sys
from pathlib import Path
sys.path.insert(0, '.')
from broker import Broker
async def main():
    b = Broker(ui_port=${UI_PORT}, instance_port=${INSTANCE_PORT},
               state_path=Path('${STATE_DIR}/state.json'))
    await b.start()
    print('SMOKE_BROKER_READY', flush=True)
    while True:
        await asyncio.sleep(3600)
asyncio.run(main())
" >"${LOG_FILE}" 2>&1
) &
BROKER_PID=$!

# Wait for ready banner (or timeout)
echo "[smoke] waiting for broker readiness..."
for i in $(seq 1 60); do
  if grep -q SMOKE_BROKER_READY "${LOG_FILE}" 2>/dev/null; then
    break
  fi
  if ! kill -0 "${BROKER_PID}" 2>/dev/null; then
    echo "[smoke] FAIL: broker exited before becoming ready" >&2
    EXIT_CODE=1
    exit 1
  fi
  sleep 0.25
done
if ! grep -q SMOKE_BROKER_READY "${LOG_FILE}" 2>/dev/null; then
  echo "[smoke] FAIL: broker did not signal readiness in time" >&2
  EXIT_CODE=1
  exit 1
fi

fail() {
  echo "[smoke] FAIL: $*" >&2
  EXIT_CODE=1
  exit 1
}

ok() {
  echo "[smoke] PASS: $*"
}

# 1. /api/status — must return 200 + JSON
code=$(curl -s -o /tmp/smoke_status.json -w '%{http_code}' "${BASE}/api/status")
[[ "${code}" == "200" ]] || fail "/api/status returned ${code}"
grep -q '"instances"' /tmp/smoke_status.json || fail "/api/status missing 'instances' key"
ok "GET /api/status (200)"

# 2. /api/state — must return 200 + JSON with the kept core collections
code=$(curl -s -o /tmp/smoke_state.json -w '%{http_code}' "${BASE}/api/state")
[[ "${code}" == "200" ]] || fail "/api/state returned ${code}"
grep -q '"messages"' /tmp/smoke_state.json || fail "/api/state missing 'messages' key"
grep -q '"channels"' /tmp/smoke_state.json || fail "/api/state missing 'channels' key"
ok "GET /api/state (200)"

# 3. /api/send — must return 200
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE}/api/send" \
       -H 'Content-Type: application/json' \
       -d '{"to":"cc1","text":"smoke ping"}')
[[ "${code}" == "200" ]] || fail "POST /api/send returned ${code}"
ok "POST /api/send (200)"

# Confirm the message landed in state
sleep 0.3
state=$(curl -s "${BASE}/api/state")
echo "${state}" | grep -q 'smoke ping' || fail "/api/send message not visible in /api/state"
ok "send-then-state round trip"

# 4. /api/clear — must return 200
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE}/api/clear")
[[ "${code}" == "200" ]] || fail "POST /api/clear returned ${code}"
ok "POST /api/clear (200)"

# Confirm messages were actually cleared
sleep 0.2
state=$(curl -s "${BASE}/api/state")
echo "${state}" | grep -q 'smoke ping' && fail "/api/clear did not actually clear messages"
ok "clear actually empties messages"

# 5. UI index page — must return 200 + some HTML
code=$(curl -s -o /tmp/smoke_index.html -w '%{http_code}' "${BASE}/")
[[ "${code}" == "200" ]] || fail "GET / returned ${code}"
grep -qi 'html' /tmp/smoke_index.html || fail "GET / did not return HTML"
ok "GET / (UI index, 200)"

echo "[smoke] all REST endpoints OK"
exit 0
