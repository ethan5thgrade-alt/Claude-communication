#!/usr/bin/env bash
# launch-multi-account.sh — spawn N Claude Code instances on one machine,
# each with its own Anthropic account, registering as distinct peers
# with the local Agent Mesh broker.
#
# Usage:
#   ./scripts/launch-multi-account.sh ROLE:EMAIL [ROLE:EMAIL ...]
#     ./scripts/launch-multi-account.sh marketing:e+m@x.com dev:e+d@x.com
#
#   ./scripts/launch-multi-account.sh --status      # list running instances
#   ./scripts/launch-multi-account.sh --kill        # stop everything
#   ./scripts/launch-multi-account.sh --kill ROLE   # stop one
#
# Each role gets:
#   - a separate CLAUDE_CONFIG_DIR (~/.claude-<role>) so account credentials
#     don't clash with other roles or with your normal `claude` setup
#   - INSTANCE_ID="cc-<role>", INSTANCE_NAME="<role>", INSTANCE_EMAIL=<email>
#   - a log file at logs/<role>.log
#   - a PID entry in logs/.pids (role=pid lines)
#
# The first time a role runs, Claude Code will open its OAuth flow in your
# browser — sign in with the intended account. The credentials persist in
# ~/.claude-<role>/ from then on, so subsequent launches are non-interactive.

set -euo pipefail

# Resolve repo root (this script lives in scripts/)
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
LOGS="$REPO/logs"
PIDS_FILE="$LOGS/.pids"
mkdir -p "$LOGS"
touch "$PIDS_FILE"

# macOS defaults to 256 file descriptors per process — 10 Claude Codes will
# blow through that. Bump it for ourselves and inherited children.
if [ "$(ulimit -n)" -lt 4096 ]; then
  ulimit -n 4096 2>/dev/null || true
fi

BROKER_URL_DEFAULT="ws://localhost:8766"

usage() {
  cat <<EOF
launch-multi-account.sh — run multiple Claude Code accounts on one machine

  $0 ROLE:EMAIL [ROLE:EMAIL ...]    launch one or more accounts
  $0 --status                       list currently-tracked instances
  $0 --kill                         stop every tracked instance
  $0 --kill ROLE                    stop one by role

env (optional):
  BROKER_URL   override the mesh broker WebSocket URL (default: $BROKER_URL_DEFAULT)
  MESH_TOKEN   shared-token auth if the broker requires it
  USE_TMUX     "1" to open each instance in a tmux pane (else nohup-detached)
EOF
}

cmd_status() {
  if [ ! -s "$PIDS_FILE" ]; then
    echo "no tracked instances."
    return 0
  fi
  printf '%-20s %-10s %-8s %s\n' ROLE PID STATE LOG
  while IFS='=' read -r role pid; do
    [ -z "$role" ] && continue
    if kill -0 "$pid" 2>/dev/null; then
      state="up"
    else
      state="dead"
    fi
    printf '%-20s %-10s %-8s %s\n' "$role" "$pid" "$state" "$LOGS/$role.log"
  done < "$PIDS_FILE"
}

cmd_kill() {
  local target="${1:-}"
  local kept="$LOGS/.pids.new"
  : > "$kept"
  while IFS='=' read -r role pid; do
    [ -z "$role" ] && continue
    if [ -n "$target" ] && [ "$role" != "$target" ]; then
      echo "$role=$pid" >> "$kept"
      continue
    fi
    if kill -0 "$pid" 2>/dev/null; then
      echo "stopping $role (pid $pid)…"
      kill "$pid" 2>/dev/null || true
      # give it a moment, then SIGKILL if needed
      sleep 0.5
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    else
      echo "$role: pid $pid already gone"
    fi
  done < "$PIDS_FILE"
  mv "$kept" "$PIDS_FILE"
}

launch_one() {
  local role="$1"
  local email="$2"

  if ! command -v claude >/dev/null 2>&1; then
    echo "error: 'claude' CLI not found on PATH. Install Claude Code first." >&2
    exit 1
  fi

  local cfg="$HOME/.claude-$role"
  mkdir -p "$cfg"

  local log="$LOGS/$role.log"
  local broker_url="${BROKER_URL:-$BROKER_URL_DEFAULT}"

  # Drop any stale entry for this role
  if [ -f "$PIDS_FILE" ]; then
    grep -v "^$role=" "$PIDS_FILE" > "$PIDS_FILE.tmp" || true
    mv "$PIDS_FILE.tmp" "$PIDS_FILE"
  fi

  echo "→ $role  ($email)"
  echo "   config:  $cfg"
  echo "   log:     $log"
  echo "   broker:  $broker_url"

  # Common env exported into the child
  local env_block=(
    CLAUDE_CONFIG_DIR="$cfg"
    INSTANCE_ID="cc-$role"
    INSTANCE_NAME="$role"
    INSTANCE_EMAIL="$email"
    INSTANCE_ROLE="$role"
    BROKER_URL="$broker_url"
  )
  [ -n "${MESH_TOKEN:-}" ] && env_block+=(MESH_TOKEN="$MESH_TOKEN")

  if [ "${USE_TMUX:-0}" = "1" ] && command -v tmux >/dev/null 2>&1; then
    # Start (or attach to) a shared session and add a window per role
    tmux has-session -t agent-mesh 2>/dev/null || tmux new-session -d -s agent-mesh -n broker
    tmux new-window -t agent-mesh -n "$role" \
      "cd '$REPO' && env ${env_block[@]} claude 2>&1 | tee '$log'"
    # tmux owns the pid; we record the tmux session name as a marker
    echo "$role=tmux:agent-mesh:$role" >> "$PIDS_FILE"
    return 0
  fi

  # Detached, log to file
  (
    cd "$REPO"
    env "${env_block[@]}" nohup claude >"$log" 2>&1 &
    echo "$role=$!" >> "$PIDS_FILE"
  )
}

# -------- arg dispatch --------
[ $# -eq 0 ] && { usage; exit 1; }

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --status)  cmd_status; exit 0 ;;
  --kill)    shift; cmd_kill "${1:-}"; exit 0 ;;
esac

for spec in "$@"; do
  role="${spec%%:*}"
  email="${spec#*:}"
  if [ -z "$role" ] || [ "$role" = "$spec" ] || [ -z "$email" ]; then
    echo "bad spec: '$spec' — expected ROLE:EMAIL" >&2
    exit 1
  fi
  launch_one "$role" "$email"
done

echo
echo "done. dashboard: http://localhost:8765   (CONNECT tab shows status)"
echo "tail logs:        tail -f $LOGS/*.log"
echo "stop everything:  $0 --kill"
