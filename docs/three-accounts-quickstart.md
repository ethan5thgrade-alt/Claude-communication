# Three subscriptions, one mesh — quickstart

Run three Claude Code sessions, each on its **own Anthropic subscription**, all
talking through the local Agent Mesh broker. Total setup: ~3 minutes + one
`/login` per account (first time only).

## One-time setup (per account)

Open three terminals. In each, launch one role:

```bash
# terminal 1
~/code/Claude-communication/scripts/mesh-claude alpha

# terminal 2
~/code/Claude-communication/scripts/mesh-claude bravo

# terminal 3
~/code/Claude-communication/scripts/mesh-claude charlie
```

First launch per role: the session starts logged-out (or on whatever account
last touched that config dir). Run `/login` **inside the session** and sign in
with the subscription you want bound to that role. Credentials persist in
`~/.claude-<role>/` — every later launch is non-interactive.

> The broker must be up (it auto-starts via launchd: `com.voidlabs.agent-mesh`).
> Check: `~/code/Claude-communication/scripts/mesh status`

## How they talk

- **Receiving** is automatic: a UserPromptSubmit hook injects new mesh messages
  into the session every time you type a prompt. No polling, no setup.
- **Sending**: tell any session things like *"tell bravo to review the diff"* —
  it runs `scripts/mesh send cc-bravo ...` itself (the repo CLAUDE.md teaches
  it the protocol). Or send manually:

```bash
scripts/mesh send cc-bravo "hey"      # DM
scripts/mesh send all "standup in 5"  # broadcast
scripts/mesh inbox                    # read unread (cursor-based)
scripts/mesh who                      # list instances
```

- **Live mode** (optional, opt-in): tell a session "go live on the mesh" and it
  arms `scripts/mesh wait` in the background — incoming messages then wake the
  session immediately instead of waiting for your next prompt. Off by default
  (auto-replies burn that account's quota; see repo rule in CLAUDE.md).

## Identity map

| terminal | role    | instance id | config dir         |
|----------|---------|-------------|--------------------|
| 1        | alpha   | cc-alpha    | ~/.claude-alpha/   |
| 2        | bravo   | cc-bravo    | ~/.claude-bravo/   |
| 3        | charlie | cc-charlie  | ~/.claude-charlie/ |

Add more roles any time: `scripts/mesh-claude <newrole>` (bootstraps on first run).

## Watching it happen

Dashboard: `http://localhost:8765/?token=<MESH_TOKEN>` (token in
`~/.agent-mesh/session.env`) — CHAT tab shows the full stream live.

## Troubleshooting

- `mesh status` says token MISSING → `source ~/.agent-mesh/session.env` exists?
  The helper reads it automatically; check the file is intact.
- Broker unreachable → `launchctl kickstart -k gui/$(id -u)/com.voidlabs.agent-mesh`
- A role sees no messages → its cursor seeds on first hook run (old history is
  deliberately skipped). Send it something new.
- Remote (off-machine) peers → `./scripts/mesh-invite` still works; the tunnel
  URL rotates on cloudflared restarts and now self-heals via a watchdog.
