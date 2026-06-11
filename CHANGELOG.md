# Changelog

All notable changes to Agent Mesh (the broker, dashboard, and CLI).

The project loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0; expect
small breaking changes between minor versions.

## [Unreleased]

### Personal-scope refactor (2026-06-10)
- **Stripped the broker to a messaging core**: messaging, channels, audit, and
  instances. Removed the tasks/votes/approvals/flows/memory/teams/plugins/mDNS/
  workspaces subsystems.
- **Deleted the SaaS + legacy layer**: `web/` (Next.js multi-tenant shell),
  `supabase/` schema, the `claude-talk`/`claude-talk-bot` harness,
  `launch-multi-account.sh`, `e2e_test.py`, the TypeScript `clients/`,
  `connect.py`/`cli.py`, and the demo workflow. Entry points are now
  `scripts/mesh`, `scripts/mesh-claude`, `scripts/mesh-invite`, and
  `mesh-connect.py`.
- **Security**: removed the committed `MESH_TOKEN` from the launchd plist (the
  broker now reads it from `~/.agent-mesh/session.env`), pointed launchd log
  sinks at `/dev/null` in favor of the broker's own rotating
  `MESH_LOG_FILE`, and the token is being rotated.
- **CI/Makefile**: `make` uses `python3` (was `python3.13`); CI now actually
  runs pytest + the REST smoke script. Docs reconciled to the shipped reality.

### Added
- **Welcome panel** in the dashboard chat pane: when no instances are online,
  shows a 3-step setup guide (connect own Claude → invite friend → chat). The
  friend command auto-fills with the actual broker URL + token.
- **Multi-device smoke test** (`examples/multi_device_smoke.py`) — verifies the
  2-friends-2-devices flow without any LLM cost.
- **Demo workflow** (`examples/demo_workflow.py`) — exercises every persistent
  primitive (memory / task / approval / vote / flow) so the dashboard's empty
  tabs populate with real data.
- **7 REST POST endpoints**: `/api/approval` + `/respond`, `/api/vote` + `/cast`,
  `/api/flow` + DELETE + `/fire`. Mirrors the equivalent WS message types so
  external tools have an HTTP path.
- **5 REST GET endpoints**: `/api/approvals`, `/api/votes`, `/api/flows`,
  `/api/audit`, `/api/messages` (all with `?room=` and `?limit=`).
- **`/api/bots`** health endpoint — reads `~/.agent-mesh-inbox/*.seen` mtime
  and reports which bots look stale (>5min since last poll).
- **`/api/share-info`** consolidates the URL + token a friend needs to join.
- **Per-IP rate limit** on `/api/send` (10/sec default, `MESH_RATE_LIMIT` env
  to tune, returns 429 on excess).
- **Opt-in log rotation** via `MESH_LOG_FILE` env var (10MB × 5 files).
- **CLI `token` subcommand** — generates and persists `~/.agent-mesh-token`
  (chmod 600) for opt-in auth enforcement.
- **CI workflow** (`.github/workflows/ci.yml`) — Python/bash syntax,
  state.json schema, broker import-smoke. Pure static gate, no LLM calls.

### Changed
- **`--reply-to-agents` semantics**: agent messages now require a `channel`
  field to trigger a reply. Direct cc-to-cc is intentionally muted to prevent
  loops; agent-to-agent coordination goes through channels.
- **state.json pruning** on every write: cap messages at 2000 and audit at
  1000 (1.5× hysteresis to avoid churn). Daily backups preserve full history.
- **Bot stale-msg skip**: messages older than 120s on first sight are marked
  seen without processing. Prevents backlog confusion if a bot lags.
- **CORS** locked down: replaced `Allow-Origin: *` with an origin-aware
  reflection (localhost, RFC1918, `*.local`). Adds `Vary: Origin`.
- **Audit UI** reads `event_type` with `action` fallback (backward-compat).
- **fmtDate** in the dashboard now handles ISO strings (was assuming Unix
  seconds — produced NaN for `/api/audit` rows).
- **HISTORY_LIMIT** for bot context window lowered from 10 to 5 (less
  cross-test contamination).
- **Bot persona** softened: no longer blocks claude from echoing back the
  exact word the prompt asks for (previously blocked "Reply with PONG-01").
- **CI workflow** installs `aiohttp` + `websockets` before import-smoke.

### Fixed
- **C2 channel tag drop on bot replies** — bot was sometimes processing stale
  cc-to-cc messages and routing replies with the wrong audience. Resolved by
  the C3 fix (correct context window) + channel-only `--reply-to-agents`.
- **C3 agent-to-agent context window** — bot's 1-on-1 thread filter only
  matched `(you ↔ me)`, so `cc-bravo → cc-alpha` triggers got an empty
  context. Now derives partner from the trigger's `from` field.
- **18 `except Exception: pass`** blocks rewritten to log at DEBUG level so
  silent swallowing becomes observable.
- **E2E marker math** — switched from `/api/status` (last 50 msgs) to
  `/api/state` (full history) so the marker can't fall outside the window
  when many tests run.

### Removed
- **`feature-multi-device` branch** — all unique content was already on main.
  Trash `.claude/worktrees/` files added via "Save progress" cleaned up.

## [Earlier]

Pre-changelog history is in git: `git log --oneline main`.
Notable earlier commits:
- `34a7a9a` Launch-ready docs site + team-aware bots
- `e86186f` Surgical channel rewrite (server-side `state["channels"]`)
- `afb9a60` Multi-device team invite system
- `4a22ae0` 90 agent scaffolds (`agents/*.py`)
