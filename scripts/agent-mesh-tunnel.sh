#!/usr/bin/env bash
# agent-mesh-tunnel.sh — keep a cloudflared quick tunnel alive in front of
# the broker's WebSocket port and capture the rotating URL into the session
# env file so `mesh-invite` can hand out a current invite.
#
# Run under launchd via com.voidlabs.agent-mesh-tunnel.plist.

set -euo pipefail

CLOUDFLARED="${CLOUDFLARED:-${HOME}/.local/bin/cloudflared}"
BROKER_LOCAL="http://localhost:8766"
SESSION_DIR="${HOME}/.agent-mesh"
SESSION_FILE="${SESSION_DIR}/session.env"
LOG_DIR="${HOME}/Library/Logs/agent-mesh"
TUNNEL_LOG="${LOG_DIR}/tunnel.cloudflared.log"

mkdir -p "${SESSION_DIR}" "${LOG_DIR}"
chmod 700 "${SESSION_DIR}"

if [[ ! -x "${CLOUDFLARED}" ]]; then
  echo "[$(date '+%FT%T%z')] cloudflared not found at ${CLOUDFLARED}" >&2
  exit 1
fi

# Run cloudflared in the foreground (launchd keeps us alive). Tee its output
# to a log so we can grep the trycloudflare URL once it appears.
: > "${TUNNEL_LOG}"

"${CLOUDFLARED}" tunnel --url "${BROKER_LOCAL}" --no-autoupdate \
  > >(tee -a "${TUNNEL_LOG}") 2>&1 &
CF_PID=$!

# Watch the log for the new URL, then patch session.env once.
(
  for _ in $(seq 1 60); do
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "${TUNNEL_LOG}" | head -n1 || true)"
    if [[ -n "${URL:-}" ]]; then
      WSS_URL="${URL/https:/wss:}"
      TMP="$(mktemp)"
      if [[ -f "${SESSION_FILE}" ]]; then
        grep -vE '^(TUNNEL_URL|BROKER_URL)=' "${SESSION_FILE}" > "${TMP}" || true
      fi
      {
        cat "${TMP}"
        echo "TUNNEL_URL=${URL}"
        echo "BROKER_URL=${WSS_URL}"
      } > "${SESSION_FILE}"
      chmod 600 "${SESSION_FILE}"
      rm -f "${TMP}"
      echo "[$(date '+%FT%T%z')] session.env updated -> ${URL}"
      break
    fi
    sleep 1
  done
) &

wait "${CF_PID}"
