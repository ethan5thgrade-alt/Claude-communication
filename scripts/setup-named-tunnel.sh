#!/usr/bin/env bash
# setup-named-tunnel.sh — one-time migration from the rotating cloudflared
# QUICK tunnel to a PERMANENT named tunnel, so:
#   - the friend invite URL never changes (quick-tunnel URLs rotate on restart)
#   - the dashboard is reachable from your phone off-LAN at a stable hostname
#   - the broker can serve the connector at <dashboard>/connect.py over the tunnel
#
# It creates two subdomains on a Cloudflare zone you own:
#   mesh.<domain>     -> the broker HTTP/dashboard (port 8765)
#   mesh-ws.<domain>  -> the broker WebSocket for friends (port 8766)
# Adding these CNAMEs does NOT touch existing records (e.g. mail/MX).
#
# PREREQ (interactive — do this FIRST, it opens a browser):
#   ~/.local/bin/cloudflared tunnel login      # pick the zone for <domain>
#
# THEN:
#   scripts/setup-named-tunnel.sh <domain>     # e.g. ethanbuildswebsites.com
#
# Re-runnable: reuses the tunnel if it already exists.
set -euo pipefail

CLOUDFLARED="${CLOUDFLARED:-${HOME}/.local/bin/cloudflared}"
TUNNEL_NAME="agent-mesh"
CF_DIR="${HOME}/.cloudflared"
CONFIG="${CF_DIR}/config.yml"
SESSION_FILE="${HOME}/.agent-mesh/session.env"
TUNNEL_PLIST="${HOME}/Library/LaunchAgents/com.voidlabs.agent-mesh-tunnel.plist"

DOMAIN="${1:-}"
if [[ -z "${DOMAIN}" ]]; then
  echo "usage: $0 <domain>   (a Cloudflare zone you own, e.g. ethanbuildswebsites.com)" >&2
  exit 2
fi
DASH_HOST="mesh.${DOMAIN}"
WS_HOST="mesh-ws.${DOMAIN}"

[[ -x "${CLOUDFLARED}" ]] || { echo "cloudflared not found at ${CLOUDFLARED}" >&2; exit 1; }
if [[ ! -f "${CF_DIR}/cert.pem" ]]; then
  echo "Not logged in to Cloudflare. Run this first (opens a browser):" >&2
  echo "  ${CLOUDFLARED} tunnel login        # pick the ${DOMAIN} zone" >&2
  echo "then re-run: $0 ${DOMAIN}" >&2
  exit 1
fi

# 1. Create the tunnel (reuse if present).
if ${CLOUDFLARED} tunnel list 2>/dev/null | grep -qE "[[:space:]]${TUNNEL_NAME}([[:space:]]|$)"; then
  echo "tunnel '${TUNNEL_NAME}' already exists — reusing"
else
  echo "creating tunnel '${TUNNEL_NAME}'..."
  ${CLOUDFLARED} tunnel create "${TUNNEL_NAME}"
fi
UUID="$(${CLOUDFLARED} tunnel list 2>/dev/null | awk -v n="${TUNNEL_NAME}" '$2==n{print $1}' | head -n1)"
[[ -n "${UUID}" ]] || { echo "could not resolve the tunnel UUID" >&2; exit 1; }

# 2. Write the ingress config (two hostnames -> two local broker ports).
mkdir -p "${CF_DIR}"
cat > "${CONFIG}" <<YAML
tunnel: ${UUID}
credentials-file: ${CF_DIR}/${UUID}.json
ingress:
  - hostname: ${DASH_HOST}
    service: http://localhost:8765
  - hostname: ${WS_HOST}
    service: http://localhost:8766
  - service: http_status:404
YAML
echo "wrote ${CONFIG}"

# 3. Point the subdomains at the tunnel (adds CNAMEs; leaves other DNS alone).
${CLOUDFLARED} tunnel route dns "${TUNNEL_NAME}" "${DASH_HOST}"
${CLOUDFLARED} tunnel route dns "${TUNNEL_NAME}" "${WS_HOST}"

# 4. Pin session.env to the permanent URLs (friends connect over the WS host).
TMP="$(mktemp)"
grep -vE '^(TUNNEL_URL|BROKER_URL)=' "${SESSION_FILE}" > "${TMP}" 2>/dev/null || true
{ cat "${TMP}"; echo "TUNNEL_URL=https://${DASH_HOST}"; echo "BROKER_URL=wss://${WS_HOST}"; } > "${SESSION_FILE}"
chmod 600 "${SESSION_FILE}"
rm -f "${TMP}"
echo "session.env -> dashboard https://${DASH_HOST} | friend wss://${WS_HOST}"

# 5. Restart the launchd tunnel; agent-mesh-tunnel.sh auto-detects the config.
if ! launchctl kickstart -k "gui/$(id -u)/com.voidlabs.agent-mesh-tunnel" 2>/dev/null; then
  launchctl unload "${TUNNEL_PLIST}" 2>/dev/null || true
  launchctl load "${TUNNEL_PLIST}"
fi

echo
echo "Done. The tunnel URL is now PERMANENT."
echo "  verify:    scripts/mesh doctor          (tunnel-url check hits ${WS_HOST})"
echo "  re-invite: scripts/mesh-invite          (URL no longer rotates)"
echo "  dashboard: https://${DASH_HOST}/?token=\$MESH_TOKEN"
