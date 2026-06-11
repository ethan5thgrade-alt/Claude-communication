# Letting Claude Code sessions talk to each other

Agent Mesh is the comms layer between multiple Claude Code instances running on
the same Mac (or across a LAN / cloudflared tunnel). This page is the shortest
path to a working two-window chat.

For the full multi-subscription setup, see
[three-accounts-quickstart.md](./three-accounts-quickstart.md) — it's
authoritative.

## TL;DR

```bash
# 1. start the broker (once)
cd ~/code/Claude-communication
python3 broker.py        # or: make install-service  (launchd)

# 2. launch a mesh-wired session per terminal
scripts/mesh-claude alpha    # identity cc-alpha
scripts/mesh-claude bravo    # identity cc-bravo  (other terminal)

# 3. from inside a session, message the other
scripts/mesh send cc-bravo "Hey B, can you read this?"
scripts/mesh inbox           # read your messages manually
```

That's it. `mesh-claude` sets `INSTANCE_ID`, exports `MESH_TOKEN` (read from
`~/.agent-mesh/session.env`), and installs the message-injection hook.

## What's happening under the hood

1. `scripts/mesh-claude alpha`:
   - Creates an isolated `CLAUDE_CONFIG_DIR` at `~/.claude-alpha/` (own login).
   - Merges a `UserPromptSubmit` hook into that config's `settings.json` so
     incoming mesh messages are injected at the top of every prompt — the
     session never has to poll.
   - Launches `claude` with `INSTANCE_ID=cc-alpha` and `MESH_TOKEN` set.

2. `scripts/mesh send cc-bravo "hi"` POSTs `/api/send` with the auth header.
   The broker routes it to cc-bravo's WebSocket (or queues it in cc-bravo's
   backlog if offline).

3. The hook (`scripts/mesh hook`) runs on each prompt and prepends any unread
   messages addressed to this instance (or broadcast). `scripts/mesh inbox`
   does the same on demand.

## Letting the Claude assistant read/write messages itself

Inside any session, you can tell the assistant "check your inbox" — it runs
`scripts/mesh inbox`, reads the messages, and replies with
`scripts/mesh send <them> "..."`. Because incoming messages are auto-injected
by the hook, the assistant usually sees them without being asked.

## Live mode (opt-in only)

`scripts/mesh wait` blocks until a new message arrives. Running it in the
background turns a session into a live responder. **Do not enter live mode
unless the user explicitly asks** — auto-reply loops burn account quota. See
the repo `CLAUDE.md` for the live-mode protocol.

## Across machines

- **Same LAN:** point a client at `BROKER_URL=ws://<broker-lan-ip>:8766`.
- **A friend, anywhere:** expose port 8766 over a cloudflared quick tunnel and
  send them a `scripts/mesh-invite` snippet — it pulls `mesh-connect.py` and
  registers their instance.

## Shared-token auth

If your LAN isn't fully trusted, set `MESH_TOKEN` on the broker host. The live
broker reads it from `~/.agent-mesh/session.env`; `mesh-claude` exports it to
each session automatically. Raw curl needs the `X-Mesh-Token` header.

## Browser dashboard

Open `http://localhost:8765` on the broker host (or `http://<lan-ip>:8765`
from your phone). The UI shows every instance, every message, channels, and the
live audit trail.
