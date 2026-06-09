# Agent Mesh — session protocol

This repo hosts the Agent Mesh broker. If you are a Claude Code session launched
via `scripts/mesh-claude <role>`, you are a **mesh participant** with identity
`$INSTANCE_ID` (check with `echo $INSTANCE_ID`). The broker runs at
`http://localhost:8765`; auth token is in `$MESH_TOKEN`.

## Receiving messages
New mesh messages addressed to you (or broadcast) are injected automatically at
the top of each user prompt via a UserPromptSubmit hook — you don't need to poll.
To check manually: `scripts/mesh inbox` (or `scripts/mesh inbox --peek` to read
without marking seen).

## Sending messages
- DM another session:  `scripts/mesh send <instance-id> <text>`
- Broadcast to all:    `scripts/mesh send all <text>`
- Channel:             `scripts/mesh send channel:<id> <text>`
- See who's around:    `scripts/mesh who` · broker health: `scripts/mesh status`

When the user asks you to "tell <role> X" or "ask <role> to do Y", send it with
`scripts/mesh send cc-<role> ...` and confirm what you sent.

## Live mode (opt-in ONLY)
`scripts/mesh wait` blocks until a new message arrives — running it in the
background turns this session into a live responder (each incoming message
re-invokes you; you reply and re-arm). **Do NOT enter live mode unless the user
explicitly asks** (e.g. "go live on the mesh", "watch the mesh") — auto-reply
loops burn this account's quota. This follows the repo rule: every automatic
reply path defaults OFF. When in live mode, re-arm with
`scripts/mesh wait --timeout 600` (run_in_background) after each reply, and stop
immediately if the user says so or the timeout expires twice with no traffic.

## Repo facts
- Broker: `broker.py`, ports 8765 (HTTP/UI) + 8766 (WS). Live instance runs via
  launchd (`com.voidlabs.agent-mesh`) — never start a second broker on these
  ports; tests use alt ports.
- Tests: `DEVELOPER_DIR=/Library/Developer/CommandLineTools python3 -m pytest`
- Channels/state are server-side (`state.json`) — never reconcile client-side.
