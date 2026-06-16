---
allowed-tools: Bash, TodoWrite
description: Post-PR branch cleanup following our safety procedures
argument-hint: [feature-branch-name]
---

Safely execute the **Post-PR Cleanup** sequence from `docs/dev/workflow/workflow-guidelines.md` for the merged feature branch "$0". That doc is authoritative for the cleanup steps; this command's added value is running them **guarded by mandatory safety checks** (clean tree, merged PR, correct branch) so nothing is deleted prematurely.

## Post-PR Cleanup Process

Execute safe branch cleanup after a PR merge:

1. **Use TodoWrite to plan cleanup steps** - Track safety-critical operations

2. **MANDATORY Safety Checks** - Execute before any cleanup:

   ```bash
   # 1. Verify the current branch is the feature branch (not the integration branch)
   git branch --show-current
   # Must show: $0 (or another feature branch pattern)
   # STOP if output shows: staging, master, or main
   ```

   ```bash
   # 2. Verify the working directory is clean (no uncommitted changes)
   git status
   if ! git diff-index --quiet HEAD --; then
     echo "SAFETY CHECK FAILED: Uncommitted changes detected"
     echo "These changes were made after the PR merge (workflow violation)"
     echo ""
     echo "Recovery options:"
     echo "1. Move to a new branch: git switch -c fix/post-merge-changes"
     echo "2. Stash for later:      git stash push -m 'Post-merge changes'"
     echo "3. Discard changes:      git restore ."
     echo ""
     echo "After handling changes, re-run: /cleanup $0"
     exit 1
   fi
   ```

   ```bash
   # 3. Verify the PR is actually merged
   gh pr view --json state,mergedAt
   # Must show: "state": "MERGED" with a "mergedAt" timestamp
   # STOP if state is not "MERGED"
   ```

3. **Cleanup Actions** - Only proceed if all safety checks pass:

   ```bash
   git checkout staging         # 4. switch to the integration branch (the PR target)
   git pull origin staging      # 5. sync with the latest remote changes
   git branch -d $0             # 6. delete the merged feature branch
   git status                   # 7. verify clean final state
   # Should show: "On branch staging" and "nothing to commit, working tree clean"
   ```

4. **Final verification** - Confirm the environment is ready for the next work:
   - On `staging` with the latest changes
   - Working directory clean
   - Feature branch successfully deleted
   - Ready for the next `/pickup`

**Critical safety requirements:**
- `docs/dev/workflow/workflow-guidelines.md` (Post-PR Cleanup) is the source of truth for the steps; if it and this command ever disagree, follow the doc and flag the discrepancy.
- NEVER proceed if a safety check fails
- Address any issue (commit changes, wait for the PR to merge, etc.) before cleanup
- Verify each step before proceeding to the next

**Feature branch to clean up:** "$0"

**If any safety check fails:**
- DO NOT proceed with cleanup actions
- **Uncommitted changes**: use the recovery options above
- **Non-merged PR**: wait for the PR to merge before cleanup
- **Wrong branch**: switch to the correct feature branch first
- Re-run `/cleanup $0` after addressing the issue

Begin the cleanup process now.
