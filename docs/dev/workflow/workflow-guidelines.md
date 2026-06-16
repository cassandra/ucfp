# Workflow Guidelines

## Branching Strategy

- **Main Branch** (`master`): stable, released code -- updated only by the
  release process (a merge from `staging`), never committed to directly.
- **Development Branch** (`staging`): active development and the PR target; the
  GitHub default branch, holding the latest code.
- **Feature Branches**: individual development work, branched from `staging`.

CI (`.github/workflows/django-tests.yml`) runs on every pull request to
`staging` (and to `master`, which receives the release merge).

## Branch Naming Conventions

| Type     | Issue? | Branch Pattern                    | Notes               |
|----------|--------|-----------------------------------|---------------------|
| feature  | YES    | feature/${ISSUE_NUM}-${MNEMONIC}  | New development     |
| bugfix   | YES    | bugfix/${ISSUE_NUM}-${MNEMONIC}   | Bug fixes           |
| docs     | YES    | docs/${ISSUE_NUM}-${MNEMONIC}     | Documentation       |
| ops      | YES    | ops/${ISSUE_NUM}-${MNEMONIC}      | Deployment/CI       |
| tests    | NO     | tests/${MNEMONIC}                 | Test-only changes   |
| refactor | YES    | refactor/${ISSUE_NUM}-${MNEMONIC} | No behavior changes |
| tweak    | NO     | tweak/${MNEMONIC}                 | Small obvious fixes |

## Development Workflow

### 1. Start from the latest `staging`
```bash
git checkout staging
git pull origin staging
```

### 2. Create a feature branch
```bash
git checkout -b feature/42-comment-pagination
```

### 3. Develop and commit
- Make logical, atomic commits with clear messages.
- Focus on **what** changed and **why**, not implementation detail.
- Do not add attributions or co-author tags.
- Do not use marketing-like language.

### 4. Push (at checkpoints and when done)
```bash
git push -u origin feature/42-comment-pagination
```

### 5. Open a pull request
Use the template at `.github/PULL_REQUEST_TEMPLATE.md`, via the GitHub CLI or web UI:

```bash
gh pr create --title "Add comment pagination" --body "$(cat <<'EOF'
## Pull Request: Add comment pagination

### Issue Link
Closes #42

### Summary
- Paginate the comment list view
- Add page-size handling to the view

### Testing
- [ ] Tests pass
- [ ] Pagination verified in the UI
EOF
)"
```

## Multi-Phase Implementation Strategy

For complex issues with multiple aspects or trade-offs:

1. **Analyze and break down** into phases:
   - Phase 1: the simple, reliable solution that fully addresses the core issue.
   - Phase 2+: optimizations, UX improvements, edge cases.
2. **Implement incrementally**: complete Phase 1 first and ensure the issue is
   FULLY resolved; commit and push, but do not open the PR yet; wait for feedback
   before Phase 2.
3. **Communicate**: post the investigation findings and phase breakdown to the issue.

Key principles: always solve the core issue first; each phase is independently
valuable; completed phases are natural review checkpoints; no PR until complete
unless explicitly asked.

## Commit Message Standards

**Good:**
```
Fix article slug generation for unicode titles
Add pagination to the comment list view
Remove deprecated ArticleStatus.DRAFT enum value
```

**MUST NOT:**
- AI/tool attribution or co-author tags.
- Implementation details in the message.

**SHOULD NOT:**
- Generic messages like "update code" or "fix bug".
- Flowery or marketing-like boasts.

## Pre-PR Requirements

**Mandatory before opening any PR:**

```bash
make lint   # real-errors lint (faster) -- must pass
make test   # full suite -- must pass
```

Run `make lint` first because it is faster, and any fixes will require re-running
`make test`. (`make check` runs lint + test + env-drift-check together.)

### PR Review Process
- **Squash and Merge**: the default for most PRs.
- **Rebase and Merge**: for well-structured PRs whose commit history is worth keeping.

## Post-PR Cleanup

After the PR is merged:

1. Verify merged: `gh pr view --json state,mergedAt`
2. Switch to staging: `git checkout staging`
3. Pull latest: `git pull origin staging`
4. Delete the branch: `git branch -d feature/42-comment-pagination`
5. Verify clean: `git status`

## Related Documentation
- Release procedures: [Release Process](release-process.md)
- Rollback procedures: [Rollback Process](rollback-process.md)
- Documentation standards: [Documentation Standards](documentation-standards.md)
- Design procedures: [Design Workflow](design-workflow.md)
