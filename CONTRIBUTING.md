# Contributing to Agent Mesh

Thanks for hacking on Agent Mesh. The codebase is small on purpose — keep
changes scoped and tested.

## Branch naming

- `batch-N` — for items from `ROADMAP.md` (one batch per worktree)
- `feat/<short-handle>` — new features outside the roadmap
- `fix/<short-handle>` — bugfixes

Avoid long-lived branches. Rebase onto `main` before opening a PR.

## Before pushing

```bash
# 1. Run the tests
python3 -m pytest tests/ -v

# 2. Smoke the REST surface
PYTHON_BIN=python3 bash scripts/smoke.sh

# 3. (Optional) Run the pre-commit hooks
pre-commit run --all-files
```

If you're touching `broker.py` or `connect.py`, the test suite is the
contract — keep it green.

## Pull request template

Use this body skeleton:

```markdown
## Summary
One or two sentences describing what changed and why.

## Test plan
- [ ] `python3 -m pytest tests/ -v` (all green)
- [ ] `bash scripts/smoke.sh` (exits 0)
- [ ] Manual smoke (if UI / interactive flow changed)
```

## Style

- Python: ruff defaults. `pre-commit` runs `ruff` (with `--fix`) and
  `ruff-format` automatically.
- No new runtime dependencies without discussion — the broker is meant to
  stay single-file installable.

## Releasing

There's no formal release process today. The `main` branch is the source
of truth.
