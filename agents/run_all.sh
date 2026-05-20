#!/usr/bin/env bash
# run_all.sh — starts all 20 agents in background with proper environment
# Usage: bash agents/run_all.sh [--stop]
#
# PIDs written to /tmp/agent-mesh-pids.txt for easy cleanup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="/tmp/agent-mesh-pids.txt"
LOG_DIR="$ROOT_DIR/logs/agents"

# ---- stop mode ----
if [[ "${1:-}" == "--stop" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        echo "Stopping agents from $PID_FILE …"
        while IFS= read -r pid; do
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" && echo "  stopped pid $pid"
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
        echo "All agents stopped."
    else
        echo "No PID file found at $PID_FILE"
        # Fallback: kill by pattern
        pkill -f "agents/0[0-2][0-9]_" 2>/dev/null && echo "Killed by pattern" || echo "No agent processes found"
    fi
    exit 0
fi

# ---- env ----
export BROKER_URL_HTTP="${BROKER_URL_HTTP:-http://localhost:8765}"
export BROKER_URL="${BROKER_URL:-ws://localhost:8766}"
export MESH_ROOM="${MESH_ROOM:-system}"
# MESH_TOKEN: leave as-is from environment (may be unset)

mkdir -p "$LOG_DIR"

echo "Starting Agent Mesh — 20 agents"
echo "  Broker HTTP : $BROKER_URL_HTTP"
echo "  Broker WS   : $BROKER_URL"
echo "  Room        : $MESH_ROOM"
echo "  Log dir     : $LOG_DIR"
echo ""

# Clear old PID file
> "$PID_FILE"

start_agent() {
    local num="$1"
    local file="$SCRIPT_DIR/${num}"
    local name="${num%.py}"
    local log="$LOG_DIR/${name}.log"

    if [[ ! -f "$file" ]]; then
        echo "  [WARN] $file not found — skipping"
        return
    fi

    python3 "$file" >> "$log" 2>&1 &
    local pid=$!
    echo "$pid" >> "$PID_FILE"
    echo "  started $name  (pid $pid)  → $log"
}

# Group 1: Core Infrastructure
start_agent "001_broker_manager.py"
start_agent "002_instance_registry.py"
start_agent "003_connection_health_monitor.py"
start_agent "004_state_persistence_manager.py"
start_agent "005_backup_agent.py"
start_agent "006_log_aggregator.py"
start_agent "007_metrics_collector.py"
start_agent "008_event_bus_manager.py"
start_agent "009_configuration_manager.py"
start_agent "010_system_clock.py"

# Group 2: Message Routing
start_agent "011_message_router.py"
start_agent "012_broadcast_manager.py"
start_agent "013_message_validator.py"
start_agent "014_message_deduplicator.py"
start_agent "015_message_priority_queue.py"
start_agent "016_message_archive.py"
start_agent "017_dead_letter_handler.py"
start_agent "018_message_transformer.py"
start_agent "019_message_rate_limiter.py"
start_agent "020_message_encryptor.py"

echo ""
echo "All 20 agents started. PIDs saved to $PID_FILE"
echo "To stop all: bash agents/run_all.sh --stop"
echo "To view logs: tail -f $LOG_DIR/*.log"
