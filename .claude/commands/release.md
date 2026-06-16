---
allowed-tools: Bash, Read, Edit, TodoWrite, Grep, Glob
description: Execute the complete release process (merge staging to master, tag, publish the GHCR image and release assets)
argument-hint: [version] (e.g., v1.2.3)
---

Execute our complete release process for version **$0**.

**`docs/dev/workflow/release-process.md` is the authoritative, step-by-step
procedure.** Read it first and follow it exactly — including the precise git/`gh`
commands, the version/CHANGELOG handling, and the validation details. The outline
below is only for orchestration; it deliberately does **not** restate the steps,
so it cannot drift from (or short-cut) the doc.

## Release for version $0

1. **Read the process doc** - Open `docs/dev/workflow/release-process.md`. It is
   the source of truth for every command and detail that follows.
2. **Plan with TodoWrite** - Turn that doc's *Prerequisites*, *Pre-Release
   Verification*, *Release Steps*, and *Post-Release* sections into trackable
   tasks, substituting `$0` as the version.
3. **Work the steps in order** - Execute each one as written in the doc, validating
   before moving on. The branch flow is develop-on-`staging`, merge `staging` →
   `master`, tag `master`; never commit to `master` directly.
4. **Post-release** - Follow the doc's *Post-Release* section. If a critical
   problem surfaces, switch to `docs/dev/workflow/rollback-process.md`.

**Critical requirements:**
- The doc is the source of truth. If this command and the doc ever disagree,
  **follow the doc and flag the discrepancy** rather than guessing.
- Verify all prerequisites before starting and validate each step before proceeding.
- Handle errors gracefully with rollback guidance.
- Use TodoWrite throughout for progress tracking.

**Version to release:** $0

Begin the release process now.
