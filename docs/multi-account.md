# Multiple Claude Code accounts on one device

Running several Claude Code subscriptions on one Mac — each signed in with a
different Anthropic email — and coordinating them through Agent Mesh.

**The authoritative guide is
[three-accounts-quickstart.md](./three-accounts-quickstart.md).** This page
just covers the why and the gotchas.

## The core idea

Each session needs two things to be a distinct mesh participant:

1. **An isolated `CLAUDE_CONFIG_DIR`** so each Anthropic login, its
   `settings.json`, hooks, and permissions don't clobber the others.
2. **A unique `INSTANCE_ID`** so the broker routes messages to the right
   session.

`scripts/mesh-claude <role>` does both: it creates `~/.claude-<role>/`,
installs the message-injection hook into that config's `settings.json`, sets
`INSTANCE_ID=cc-<role>`, and exports `MESH_TOKEN`. One terminal = one role =
one subscription. First launch per role, run `/login` inside the session.

## What the mesh handles vs. what you handle

- **Mesh handles:** message routing by `INSTANCE_ID`, online/offline status,
  the audit trail (broker stamps the sender, so identity can't be forged by a
  client), channels for grouping a subset of instances, and an offline backlog
  per instance.
- **You handle (OS / Claude Code):** the actual Anthropic logins, per-account
  rate limits and billing, keeping instances in separate working directories
  (use git worktrees to avoid commit races), and not leaking secrets in
  plain-text messages.

## Quick start

```bash
# 1. start the broker once
python3 broker.py        # or: make install-service  (launchd)

# 2. one terminal per account
scripts/mesh-claude marketing
scripts/mesh-claude dev
scripts/mesh-claude ops
```

Then message between them with `scripts/mesh send cc-dev "..."`. See
[three-accounts-quickstart.md](./three-accounts-quickstart.md) for the full
walk-through.
