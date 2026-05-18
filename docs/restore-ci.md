# Restoring CI

The CI workflow lives at `.github/ci.yml.disabled`. To activate it:

1. In a real Terminal (not Claude Code's shell), refresh gh auth with the workflow scope:
   ```
   gh auth refresh -s workflow
   ```
2. Move the file back to its canonical path:
   ```
   git mv .github/ci.yml.disabled .github/workflows/ci.yml
   git commit -m "Re-enable CI workflow"
   git push
   ```

Or, if you prefer the web UI: open `.github/ci.yml.disabled` on GitHub, click the rename pencil, change the path to `.github/workflows/ci.yml`, and commit.
