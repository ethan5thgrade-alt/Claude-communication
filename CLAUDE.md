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
- Pipe a big payload:  `git diff | scripts/mesh send <id> -`  (text `-` reads stdin)
- See who's around:    `scripts/mesh who` · broker health: `scripts/mesh status`

When the user asks you to "tell <role> X" or "ask <role> to do Y", send it with
`scripts/mesh send cc-<role> ...` and confirm what you sent.

## Asking a peer and waiting for the answer
`scripts/mesh ask <peer> <question>` sends the question and BLOCKS until that
peer replies to you (ignores unrelated traffic; `--timeout SECS`, default 120).
When a message you receive starts with `[ask]`, reply to the sender with
`scripts/mesh send <sender> ...` — the asker is blocked on your reply. (This
closes the loop through the normal hook; it is not an auto-reply path — you, the
session, still choose to answer, so it stays within the all-reply-paths-OFF rule.)

## Focus + handoff (continuity across sessions)
- `scripts/mesh focus <text>` — record what you're working on; shows in `who`
  and the dashboard so other sessions know you're alive and on what.
- `scripts/mesh handoff <text|->` — leave a note your NEXT session under this id
  reads once on startup. Before ending multi-step work, run
  `scripts/mesh handoff -` and pipe a short "done / in-flight / resume-at" summary.

## Live mode (opt-in ONLY)
`scripts/mesh wait` blocks until a new message arrives — running it in the
background turns this session into a live responder (each incoming message
re-invokes you; you reply and re-arm). **Do NOT enter live mode unless the user
explicitly asks** (e.g. "go live on the mesh", "watch the mesh") — auto-reply
loops burn this account's quota. This follows the repo rule: every automatic
reply path defaults OFF. When in live mode, re-arm with
`scripts/mesh wait --timeout 600` (run_in_background) after each reply, and stop
immediately if the user says so or the timeout expires twice with no traffic.

## If messaging goes quiet
The hook fails silently by design (never breaks a prompt), but after 3 missed
prompts it prints one line telling you to run `scripts/mesh doctor` — a full
self-check of broker/ports/launchd/tunnel/token with a fix hint per failure.

## Repo facts
- Broker: `broker.py`, ports 8765 (HTTP/UI) + 8766 (WS). Live instance runs via
  launchd (`com.voidlabs.agent-mesh`) — never start a second broker on these
  ports; tests use alt ports. The broker is messaging-only (DMs, channels,
  audit, presence) — the old tasks/votes/approvals/flows/memory/plugins surface
  was removed as unused.
- Token: lives only in `~/.agent-mesh/session.env`; the broker reads it from
  there (the launchd plist no longer embeds it). Never commit it.
- Tests: `DEVELOPER_DIR=/Library/Developer/CommandLineTools python3 -m pytest`
- Channels/state are server-side (`state.json`) — never reconcile client-side.
