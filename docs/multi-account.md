# Multiple Claude Code accounts on one device

This is the canonical guide for running **multiple Claude Code subscriptions on
the same physical machine, each signed in with a different Anthropic email**,
and coordinating them through Agent Mesh.

Each row is one real-world issue or use case. **Mesh ✓** = handled out of the
box. **Mesh ⚠** = partially handled or workaround needed. **Mesh ✗** = caller's
responsibility (OS, Claude Code, or Anthropic).

---

## A. Identity & Auth (Anthropic side)

| # | Use case / issue | Status |
|---|---|---|
| 1 | One user has Pro + Max + API accounts on different emails, wants to use all simultaneously | ✗ caller — separate `CLAUDE_CONFIG_DIR` per account |
| 2 | `claude /login` overwrites credentials — only one account active per config dir | ✗ caller — use launcher script |
| 3 | Tokens stored at `~/.claude/.credentials` clash across accounts | ✗ caller — `CLAUDE_CONFIG_DIR` isolates |
| 4 | OAuth refresh tokens expire mid-session, instance silently breaks | Mesh ✓ — broker reports instance offline; user re-runs `claude` to refresh |
| 5 | MFA / 2FA prompt blocks an automated re-login | ✗ caller — re-login is interactive by design |
| 6 | Account banned/suspended mid-task | Mesh ✓ — task stays in `in_progress`, retry-able |
| 7 | Plan tier differences — Pro vs Max vs API — affect model choice | Mesh ⚠ — label per instance, but no auto-routing |
| 8 | Free tier limit hit, instance stops responding | Mesh ✓ — surfaces as no-reply; sender can broadcast to others |
| 9 | Anthropic password change invalidates all sessions | ✗ caller |
| 10 | User wants to alias one account as "marketing" and another as "dev" | Mesh ✓ — `INSTANCE_NAME` env var |

## B. Filesystem & Config isolation

| # | Use case / issue | Status |
|---|---|---|
| 11 | `~/.claude/settings.json` is shared, not per-account | ✗ caller — `CLAUDE_CONFIG_DIR=~/.claude-marketing` |
| 12 | `~/.claude/CLAUDE.md` global instructions leak across accounts | ✗ caller — per-config-dir |
| 13 | Auto-memory at `~/.claude/projects/.../memory/` shared if same CWD | ⚠ — use distinct CWDs per account |
| 14 | MCP server configs in settings collide | ✗ caller — per-config-dir |
| 15 | Hooks fire for every instance on the machine | ✗ caller — gate hooks by `INSTANCE_ID` |
| 16 | Statusline applies globally | ✗ caller — per-config-dir |
| 17 | Permission allow/deny lists mix | ✗ caller — per-config-dir |
| 18 | Skills in `~/.claude/skills/` are shared | ⚠ caller — usually fine (skills are non-state) |
| 19 | Plugin cache `~/.claude/plugins/cache/` shared | Mesh ✓ — broker plugin bridge scans once, instances reference by name |
| 20 | One instance's worktree confuses another instance's git ops | ⚠ — keep instances in separate CWDs |

## C. Agent Mesh instance identity

| # | Use case / issue | Status |
|---|---|---|
| 21 | Default `INSTANCE_ID` is hardcoded `cc1` — 5 instances collide | Mesh ✓ — launcher sets unique IDs |
| 22 | Need stable IDs across restarts (don't spawn ghosts) | Mesh ✓ — launcher uses email-derived slug |
| 23 | Display the Anthropic email next to each instance in the dashboard | Mesh ✓ — `INSTANCE_EMAIL` env var, shown on agent card |
| 24 | Mesh handshake can't verify which account an instance claims | Mesh ⚠ — trust-on-first-use; future: per-instance token |
| 25 | Restart should reclaim same ID, not spawn duplicate | Mesh ✓ — broker dedupes on `id` |
| 26 | Roles per instance (frontend / backend / QA) | Mesh ✓ — `INSTANCE_ROLE` env, settable via UI |
| 27 | Per-instance MESH_TOKEN to prevent spoofing | Mesh ⚠ — single shared token currently |
| 28 | Identity survives reboot via launchd | Mesh ✓ — plist template |
| 29 | Multiple sessions for one account = one instance or many? | Mesh ✓ — one `INSTANCE_ID` = one instance; new session reconnects |
| 30 | Naming scales (`cc-ethan-marketing`, `cc-ethan-dev`) | Mesh ✓ — free-form |

## D. Process orchestration

| # | Use case / issue | Status |
|---|---|---|
| 31 | Launch 5 Claude Codes at once from one command | Mesh ✓ — `scripts/launch-multi-account.sh` |
| 32 | Each needs unique `CLAUDE_CONFIG_DIR` | Mesh ✓ — launcher sets it |
| 33 | Auto-start all instances when broker boots | Mesh ⚠ — manual today; launchd template extendable |
| 34 | Per-instance log files (no interleaving) | Mesh ✓ — launcher writes to `logs/<id>.log` |
| 35 | Graceful shutdown of all instances | Mesh ✓ — launcher tracks PIDs in `logs/.pids` |
| 36 | PID file conflicts | Mesh ✓ — PIDs keyed by `INSTANCE_ID` |
| 37 | CPU/memory pressure from 5 LLM clients | ✗ caller — OS resource limits |
| 38 | Detect crashed instance and respawn | Mesh ⚠ — broker marks offline; respawn is manual |
| 39 | `claude update` per config dir | ✗ caller — run per dir |
| 40 | Terminal output collision in one shell | Mesh ✓ — launcher uses tmux panes or `nohup` to log files |

## E. Communication & messaging

| # | Use case / issue | Status |
|---|---|---|
| 41 | `@cc1` ambiguous when 5 exist — need clear names | Mesh ✓ — use `INSTANCE_NAME` mentions |
| 42 | Broadcast bills 5 separate accounts | Mesh ⚠ — yes, intentional; UI shows cost |
| 43 | Account A delegates task to account B — B's tokens pay | Mesh ✓ — explicit; auditable |
| 44 | Reply attribution lands at the right account | Mesh ✓ — broker routes by `INSTANCE_ID` |
| 45 | Chat history per-instance or global? | Mesh ✓ — global stream; filterable by sender in UI |
| 46 | Mention syntax: `@email` / `@role` / `@id` | Mesh ⚠ — `@id` only today |
| 47 | Threading replies to specific message | Mesh ⚠ — no native threading yet |
| 48 | Rooms / channels with subsets of instances | Mesh ⚠ — `feature-multi-device` branch has invite codes |
| 49 | Clear visual difference between direct and broadcast | Mesh ✓ — broadcast bar + red border in compose |
| 50 | Offline instance backlog | Mesh ✓ — byte-budgeted per-instance backlog |

## F. Rate limits & billing

| # | Use case / issue | Status |
|---|---|---|
| 51 | 5 accounts = 5x effective rate limit | Mesh ✓ — parallelism is the point |
| 52 | One account hits limit, others unaffected | Mesh ✓ — independent connections |
| 53 | Track cost per account in dashboard | Mesh ⚠ — not yet; future |
| 54 | Switch active account mid-task | Mesh ✓ — same broker, different sender |
| 55 | Audit log shows which account did what | Mesh ✓ — `from` field in audit table |
| 56 | Token usage per instance visible | Mesh ⚠ — Claude Code reports usage; not piped to broker |
| 57 | Budget alerts per account | Mesh ✗ — out of scope |
| 58 | Auto-failover to least-utilized account | Mesh ⚠ — manual today; could be a flow |
| 59 | Plan tier gates model access | ✗ caller — Anthropic enforces |
| 60 | API key vs OAuth bills differently | ✗ caller |

## G. Working directory / project isolation

| # | Use case / issue | Status |
|---|---|---|
| 61 | Two instances in same CWD edit same file simultaneously | ⚠ — coordinate via tasks; use worktrees |
| 62 | Git race condition (two `git commit` calls) | ⚠ — use worktrees per instance |
| 63 | Different CWDs, shared work via broker memory | Mesh ✓ — `broker_memory()` |
| 64 | Worktrees for parallel branches | Mesh ⚠ — caller manages; `.claude/worktrees/` convention |
| 65 | File locking | ✗ caller |
| 66 | Lockfile conflicts (npm, pip) | ✗ caller |
| 67 | Shared SQLite — WAL mode | ✗ caller |
| 68 | Test runs collide on ports | ✗ caller |
| 69 | Build artifacts overwritten | ✗ caller |
| 70 | `.env` secret leakage across accounts | ✗ caller — use per-instance `.env` |

## H. Permissions & approvals

| # | Use case / issue | Status |
|---|---|---|
| 71 | `broker_approve_and_wait` — who approves when 5 instances? | Mesh ✓ — human via UI; or another instance via `broker_approve_decision` |
| 72 | Each account has own permissions, but settings.json shared | ✗ caller — per-config-dir fixes |
| 73 | Approval routing: human or instance-owner | Mesh ✓ — `to` field on approval request |
| 74 | Auto-approve list per account | Mesh ⚠ — global today |
| 75 | Hook permissions vs mesh permissions | ✗ caller |
| 76 | Read-only vs read-write roles | Mesh ⚠ — `INSTANCE_ROLE` is advisory only |
| 77 | Manager approves worker's actions | Mesh ✓ — `broker_approve_and_wait(to="manager")` |
| 78 | Voting — one vote per account or per session? | Mesh ✓ — one vote per `INSTANCE_ID` |
| 79 | Audit shows authoritative identity | Mesh ✓ — broker stamps sender |
| 80 | Pause/resume one instance without affecting others | Mesh ✓ — STOP/RESUME header buttons |

## I. UX / dashboard

| # | Use case / issue | Status |
|---|---|---|
| 81 | Sidebar shows 5 instances with email labels | Mesh ✓ — email displayed on agent card |
| 82 | Color-coding per account | Mesh ⚠ — per-instance role color exists; per-email future |
| 83 | Per-instance avatars (Gravatar of email) | Mesh ⚠ — future |
| 84 | Filter chat by account | Mesh ✓ — click instance in sidebar |
| 85 | Switch "viewing as" account | Mesh ⚠ — dashboard is operator-only |
| 86 | Mobile: 5 instances on a small screen | Mesh ✓ — horizontal pill strip |
| 87 | Notifications attributable to account | Mesh ⚠ — single notify channel today |
| 88 | Account switcher (click avatar) | Mesh ⚠ — future |
| 89 | Status per account (online / offline / limit-reached) | Mesh ✓ — connection dot, workload bar |
| 90 | Cost dashboard per account | Mesh ⚠ — future |

## J. Security & access control

| # | Use case / issue | Status |
|---|---|---|
| 91 | Instance A spoofs ID of Instance B | Mesh ⚠ — single token today; per-instance token planned |
| 92 | `MESH_TOKEN` leaked via env logs | ✗ caller — don't `env` dump |
| 93 | Reading another account's memory | Mesh ⚠ — memory is global; rooms planned |
| 94 | Command injection via mesh messages | Mesh ✓ — no eval; messages are strings |
| 95 | Audit log can't be forged | Mesh ✓ — broker stamps, not client |
| 96 | Secrets in messages leak across accounts | ⚠ — caller's responsibility; broker is plain text |
| 97 | Disconnect a compromised instance | Mesh ✓ — `POST /api/instances/<id>/kick` (or via UI) |
| 98 | Account takeover via MCP server | ✗ caller — vet MCP servers |
| 99 | Cross-instance code execution | Mesh ✓ — broker never executes client code |
| 100 | Backup encryption — `state.json` plaintext | ⚠ — encrypt at filesystem level |

---

## Quick start: run 3 accounts on one Mac

```bash
# 1. start the broker once
python3 broker.py &

# 2. spawn three Claude Code instances, each on its own account
./scripts/launch-multi-account.sh \
  marketing:ethan+marketing@example.com \
  dev:ethan+dev@example.com \
  ops:ethan+ops@example.com
```

The launcher creates `~/.claude-<role>/` config dirs, sets `INSTANCE_ID`,
`INSTANCE_NAME`, `INSTANCE_EMAIL`, `INSTANCE_ROLE`, and `BROKER_URL`, then
opens each instance in a tmux pane (or detached `nohup` if tmux is missing).
Logs land in `logs/<role>.log`; PIDs in `logs/.pids`.

## Tearing it down

```bash
./scripts/launch-multi-account.sh --kill
```
