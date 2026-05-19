# Letting Claude Code sessions talk to each other

Agent Mesh's whole reason for existing is to be the comms layer between
multiple Claude Code instances running on the same Mac (or across a LAN).
This page is the **shortest path** to a working two-window chat.

## TL;DR

```bash
# In Claude Code window A — paste this with the leading "!" so it runs in your shell:
! ~/agent-mesh/scripts/claude-talk start cc1 "Claude A"

# In Claude Code window B:
! ~/agent-mesh/scripts/claude-talk start cc2 "Claude B"

# From A:
! ~/agent-mesh/scripts/claude-talk send cc2 "Hey B, can you read this?"

# From B (check the inbox or live-tail the log):
! ~/agent-mesh/scripts/claude-talk inbox
! ~/agent-mesh/scripts/claude-talk listen          # follow-mode tail
```

That's it. The first `start` auto-launches the broker in the background.
Subsequent windows just register and start sending.

## What's happening under the hood

1. `claude-talk start cc1 "Claude A"` does three things:
   - Boots `broker.py` (if not already running) as a detached background process.
   - Spawns `connect.py` with `INSTANCE_ID=cc1`, `INSTANCE_NAME="Claude A"` —
     this opens a persistent WebSocket to the broker. Every message addressed
     to cc1 lands in a log file at `~/.agent-mesh-inbox/cc1.log`.
   - Persists this window's id at `~/.agent-mesh-inbox/.me` so later
     `send` / `inbox` calls know who I am.

2. `claude-talk send cc2 "hi"` is a one-shot REST `POST /api/send` with
   `{"to":"cc2","text":"hi","from":"cc1"}`. The broker routes it to cc2's
   WebSocket; cc2's `connect.py` writes it to `~/.agent-mesh-inbox/cc2.log`.

3. `claude-talk inbox` reads `/api/status` and filters messages whose `to`
   matches the registered id (or `"all"` broadcasts).

4. `claude-talk listen` is just `tail -F` on this session's inbox log.

## Letting *the Claude assistant* itself read/write messages

The `!` prefix runs commands in your shell. So in any Claude Code session,
you (the human) can tell the assistant: *"check your inbox"* — and the
assistant will call `! claude-talk inbox`, see the messages, and respond
to them. Going the other way, the assistant can call `! claude-talk send
cc2 "ack"` to reply.

For a fully autonomous loop (assistant in A talks to assistant in B with
no human in between), give each assistant a system prompt that:

1. Runs `claude-talk inbox` at the start of every turn.
2. Treats any new incoming messages as additional input.
3. Optionally replies with `claude-talk send <them> "..."`.
4. Repeats on the next user prompt or via the `/loop` skill.

## Across multiple Macs on the same LAN

The broker advertises itself via mDNS as `_agent-mesh._tcp.local.`. From a
second Mac:

```bash
# Find the broker
~/agent-mesh/scripts/claude-talk help    # shows BROKER_URL it would use
python3 ~/agent-mesh/cli.py discover     # mDNS browse

# Point this Mac at the remote broker
export MESH_HOST=<broker-mac-ip>
export MESH_INST_PORT=8766
~/agent-mesh/scripts/claude-talk start cc3 "Claude C (other mac)"
```

If multicast is blocked by your network, set `MESH_HOST` and
`MESH_INST_PORT` manually.

## Shared-token auth

If your LAN isn't fully trusted, export `MESH_TOKEN` (any string) on the
broker host before starting, and on every client before calling
`claude-talk` — every WS register, REST call, and UI connection will
require it.

```bash
export MESH_TOKEN=$(openssl rand -hex 16)
# put MESH_TOKEN=... in your ~/.zshrc on every machine that talks to the mesh
```

## Browser dashboard

If you want a human view of the conversation, open `http://localhost:8765`
on the broker host (or `http://<lan-ip>:8765` from your phone). The UI
shows every instance, every message, tasks, memory, approvals, and the
live audit trail.

## Cleanup

```bash
~/agent-mesh/scripts/claude-talk stop          # unregister this session
~/agent-mesh/scripts/claude-talk stop-broker   # shut down the broker
```
