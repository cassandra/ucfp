# Rollback Process

> **Role**: Process Documentation
> **Purpose**: How to roll back a problematic published release

Rollback re-points the GHCR `latest` tag at a previous good image and marks the
bad release, so self-host users who run `update.sh` pull the good version again.
It is driven by the `.github/workflows/rollback.yml` workflow.

## When to Rollback vs Hotfix

### Rollback when:
- A **critical security vulnerability** shipped in the new release.
- **Data corruption** or database issues.
- The **application will not start** or crashes immediately.
- **Major functionality is broken** and affects most users with no quick fix.

### Hotfix when:
- **Minor bugs** that do not prevent normal operation.
- Issues affecting a **subset of users** or specific configurations.
- A **quick fix is available** (roughly < 2 hours to implement and test).

**When in doubt, rollback first** -- it is easier to roll back immediately and
decide on a fix afterward than to leave more users affected.

## Rollback Execution

### Prerequisites
- Identify the **last known good version** (a previous release tag).
- Confirm the **bad version** to mark.
- Have admin access to the repository (to dispatch the workflow).

### Steps
1. **Open the workflow**: repository Actions -> "Rollback Release".
2. **Run workflow** with inputs:
   - **rollback_to_version**: the previous good version (e.g. `v1.3.0`).
   - **bad_version**: the version to mark (e.g. `v1.4.0`).
   - **reason**: a brief description (e.g. "Critical migration issue").
3. **Monitor** the run to completion.
4. **Verify**:
   - GHCR `latest` now points at the rollback version.
   - The bad release is marked "DO NOT USE - ROLLED BACK".
   - A tracking issue was created.

### What the workflow does automatically
- Pulls `ghcr.io/cassandra/ucfp:<rollback_to_version>` and re-tags it `:latest`,
  then pushes `:latest`.
- Edits the bad release: prepends a rollback notice, marks it a prerelease to
  de-emphasize it.
- Opens a tracking issue (labels: `rollback`, `critical`).

## Post-Rollback Actions

### Immediate (within 1 hour)
- [ ] Verify `update.sh` now pulls the rollback version.
- [ ] Communicate the incident (Discussions / external channels).
- [ ] Watch for reports about the rollback itself.

### Short-term (within 24 hours)
- [ ] Investigate the root cause in the bad release.
- [ ] Plan the fix and start a fix branch.

### Medium-term (within 1 week)
- [ ] Implement and thoroughly test the fix.
- [ ] Cut a new patched release ([Release Process](release-process.md)).
- [ ] Write a post-mortem for major incidents.

## Rollback Limitations

Re-tagging an image **cannot** undo:
- Database migrations that destroyed data.
- Problems needing manual per-user intervention.
- Damage to user-specific configuration or data files.
- Third-party service integration issues.

In those cases, additional recovery beyond the automated rollback is required.

## Related Documentation
- Release procedures: [Release Process](release-process.md)
- Workflow guidelines: [Workflow Guidelines](workflow-guidelines.md)
