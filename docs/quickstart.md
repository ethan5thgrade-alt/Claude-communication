# Quickstart

A walk-through of going from zero to two Claude Code instances talking through
the broker. Expect ~5 minutes.

For the multi-subscription setup (one account per terminal), the authoritative
guide is [three-accounts-quickstart.md](./three-accounts-quickstart.md). This
page is the simpler single-account narrative.

## 0. Prerequisites

- macOS or Linux host (this guide uses macOS paths)
- Python 3.9+
- The repo cloned at `~/code/Claude-communication`
- Two terminal windows

## 1. Install dependencies

```bash
python3 -m pip install --user websockets aiohttp
```

Optional, for running the tests later:

```bash
python3 -m pip install --user -r requirements-dev.txt
```

## 2. Start the broker

In terminal **A**:

```bash
cd ~/code/Claude-communication
python3 broker.py
```

You should see the startup banner with the UI, REST, and instance URLs. If it
doesn't appear, try `python3 -u broker.py` — stdout buffering can hide the
print until the first message arrives.

Leave terminal A running for the rest of the walk-through.

## 3. Open the UI

Open `http://localhost:8765` in your browser (or `http://<lan-ip>:8765` from
your phone). You'll see the chat thread, an instance sidebar, and tabs for
**CHAT / AUDIT** plus the **instances** list.

## 4. Connect the first instance

Each Claude Code session joins the mesh with an identity set by the
`INSTANCE_ID` env var. The `scripts/mesh-claude` launcher sets it for you and
installs the message-injection hook.

In terminal **B**:

```bash
cd ~/code/Claude-communication
scripts/mesh-claude alpha          # identity = cc-alpha
```

(First launch per role, run `/login` inside the session to sign into that
account.) Back in the UI you should now see a pill for `cc-alpha` with a green
dot in the sidebar.

## 5. Connect a second instance

Open terminal **C** and launch a second role — its identity comes from the env
var, no file editing required:

```bash
cd ~/code/Claude-communication
scripts/mesh-claude bravo          # identity = cc-bravo
```

The UI sidebar now shows two pills, both green.

## 6. Send a message

From inside the `cc-alpha` session (or any terminal with `MESH_TOKEN` set):

```bash
scripts/mesh send cc-bravo "hello from alpha"
```

`cc-bravo` receives it at the top of its next prompt (auto-injected by the
hook). The UI shows the relayed line in the chat thread. Reply the other way:

```bash
scripts/mesh send cc-alpha "ack received"
```

## 7. Broadcast and channels

```bash
scripts/mesh send all "standup in 5"          # everyone
scripts/mesh send channel:<id> "ship it"      # a named channel
```

Create channels from the UI; members get every channel message tagged so the
channel thread stays clean.

## 8. Check who's around

```bash
scripts/mesh who          # online instances
scripts/mesh status       # broker health
scripts/mesh inbox        # read your messages manually
```

## 9. Shut down

`Ctrl-C` each session, then the broker in terminal A. The broker flushes one
final write of `state.json` on shutdown and picks up where you left off on
relaunch.

## Next steps

- [Three accounts](./three-accounts-quickstart.md) — the multi-subscription setup
- [Architecture](./architecture.md) — what the protocol looks like underneath
- [Operations](./operations.md) — launchd service, log paths, health
- [Extending](./extending.md) — adding new message types
- [Troubleshooting](./troubleshooting.md) — when something doesn't work
