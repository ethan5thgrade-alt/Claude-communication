# Agent Mesh — Agents Directory

This directory contains 20 Python agent scripts that connect to the local Claude-communication broker and perform specialized roles within the mesh.

## Architecture

Each agent:
- Registers with the broker via `connect.py` (WebSocket on port 8766)
- Polls the broker REST API (HTTP on port 8765) to perform its work
- Responds to direct messages sent to its `AGENT_ID`
- Emits broadcasts/alerts to the `system` room

## Starting Agents

### Start all 20 agents at once

```bash
cd ~/Claude-communication
bash agents/run_all.sh
```

### Start a single agent

```bash
cd ~/Claude-communication
BROKER_URL_HTTP=http://localhost:8765 python3 agents/001_broker_manager.py
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BROKER_URL_HTTP` | `http://localhost:8765` | Broker REST API base URL |
| `BROKER_URL` | `ws://localhost:8766` | Broker WebSocket URL |
| `MESH_TOKEN` | (none) | Shared auth token |
| `MESH_ROOM` | `system` | Default room for agents |

## Agent Roster

### Group 1: Core Infrastructure

| # | File | Role | Poll Interval |
|---|---|---|---|
| 001 | `001_broker_manager.py` | Monitors broker health, auto-restarts on 3 consecutive failures | 30s |
| 002 | `002_instance_registry.py` | Tracks connected instances, fires joined/left events | 15s |
| 003 | `003_connection_health_monitor.py` | Pings all instances, alerts on offline >2 cycles | 60s |
| 004 | `004_state_persistence_manager.py` | Validates `state.json` integrity, restores from backup | 5min |
| 005 | `005_backup_agent.py` | Creates hourly dated backups of `state.json`, keeps last 24 | 60s |
| 006 | `006_log_aggregator.py` | Appends audit entries to daily JSONL files in `logs/` | 30s |
| 007 | `007_metrics_collector.py` | Parses Prometheus metrics, stores 24h time-series, fires threshold alerts | 60s |
| 008 | `008_event_bus_manager.py` | Routes `event:*` broadcasts to registered subscribers | 10s |
| 009 | `009_configuration_manager.py` | Checks token/port config, warns if misconfigured | 5min |
| 010 | `010_system_clock.py` | Publishes heartbeats, fires cron-scheduled tasks | 60s |

### Group 2: Message Routing

| # | File | Role | Poll Interval |
|---|---|---|---|
| 011 | `011_message_router.py` | Routes `route:<intent>` messages to best-matching agent | 5s |
| 012 | `012_broadcast_manager.py` | Detects broadcast spam (>10/min), supports per-instance muting | 10s |
| 013 | `013_message_validator.py` | Validates message payloads for required fields, size, type | 30s |
| 014 | `014_message_deduplicator.py` | Detects duplicate messages (same sender+text within 60s) | 30s |
| 015 | `015_message_priority_queue.py` | Delivers URGENT/CRITICAL/HIGH prefixed messages immediately | 5s |
| 016 | `016_message_archive.py` | Archives all messages to daily JSONL files in `archive/` | 5min |
| 017 | `017_dead_letter_handler.py` | Queues messages to offline instances, redelivers on reconnect | 60s |
| 018 | `018_message_transformer.py` | Transforms messages: JSON, bullets, summary, formal, casual | 30s (reactive) |
| 019 | `019_message_rate_limiter.py` | Warns at 30/min, alerts at 60/min per instance | 10s |
| 020 | `020_message_encryptor.py` | XOR-encrypts messages with MESH_TOKEN key + HMAC + nonce | 30s (reactive) |

## Message Protocol

Send commands to an agent with:
```
POST /api/send
{"to": "agent_001_broker_manager", "text": "broker_status"}
```

Or via CLI:
```bash
python3 cli.py send agent_001_broker_manager "broker_status"
```

## Directory Structure

```
~/Claude-communication/
├── agents/          ← this directory
├── backups/         ← state.json backups (agent 005)
├── logs/            ← audit JSONL logs (agent 006)
├── archive/         ← message archives (agent 016)
├── schedules.json   ← cron schedules (agent 010)
├── state.json       ← broker state
├── broker.py        ← broker server
└── connect.py       ← shared WebSocket client
```

## Stopping Agents

```bash
# Kill all agent processes
pkill -f "agents/0[0-2][0-9]_"

# Or use the PIDs written by run_all.sh
cat /tmp/agent-mesh-pids.txt | xargs kill
```
