# Rollback Process

> **Role**: Process Documentation
> **Purpose**: How to roll back a bad release — re-point `latest` at the last good
> image, then re-deploy the droplet from it

Both deployment lanes track the **`latest`** tag: the production droplet
(`landfall.cassandrahq.com`) runs `ghcr.io/cassandra/ucfp:latest`, and self-hosters
pull `:latest` when they run `update.sh`. So a rollback is one idea, done in one
place: **make `latest` point at the last good image again.** That single registry
change fixes both lanes — the droplet just re-pulls `latest` like a normal deploy,
and self-host updates stop handing out the bad image.

We deliberately roll back this way — re-pointing `latest` — rather than pinning the
droplet to a specific old version. The droplet always deploys `latest`; nothing on
it needs editing, and there is no version to remember to un-pin later.

The rollback is a **runbook, not an automation**: a short sequence of validated
commands with a sanity check after each.

## When to roll back vs hotfix

### Roll back when
- A **critical security vulnerability** shipped.
- **Data corruption** or a database problem.
- The **application will not start** or crashes immediately.
- **Major functionality is broken** for most users with no quick fix.

### Hotfix (roll forward) when
- **Minor bugs** that do not prevent normal operation.
- Issues affecting a **subset of users** or specific configurations.
- A **quick fix is available** (roughly < 2 hours to implement, test, and release).

**When in doubt, roll back first.** Restoring the last-known-good version is fast
and low-risk; you can diagnose and roll forward once things are stable.

---

## Rollback runbook

### Prerequisites
- The **last-known-good version** tag (e.g. `v0.0.6`) — call it `<GOOD>` below.
- Admin access to the repository (to dispatch the workflow).
- SSH access to the droplet (the `cassandrahq.com` alias, `/opt/ucfp`, from
  [Droplet Setup](../project/droplet-setup.md)).
- Read **Migrations & data** below *before* you start if the bad release included a
  migration — re-pointing the image does not undo a migration that already ran.

### 1. Confirm the good version
List the published releases and pick the newest tag that predates the bad one:

```bash
gh release list --limit 5
```

Confirm that image still exists in the registry (the workflow will pull it):

```bash
gh api /orgs/cassandra/packages/container/ucfp/versions \
  --jq '.[].metadata.container.tags[]' | grep '<GOOD>'
```

### 2. Re-point `latest` at the good image
Run the **Rollback Release** workflow (`.github/workflows/rollback.yml`):
**Actions → "Rollback Release" → Run workflow**, with inputs:
- **rollback_to_version**: `<GOOD>` (e.g. `v0.0.6`).
- **bad_version**: the version being pulled (e.g. `v0.0.7`).
- **reason**: a brief description (e.g. "App crashes on startup").

Monitor the run to completion, then verify its effects:
- GHCR `latest` now resolves to `<GOOD>`.
- The bad release is retitled "⚠️ DO NOT USE - ROLLED BACK" and marked a prerelease.
- A tracking issue was opened (labels `rollback`, `critical`).

This re-tags `<GOOD>` as `:latest` and pushes it, so the registry is now correct for
**both** the droplet (step 3) and self-hosters (immediately, on their next update).

### 3. Re-deploy the droplet from `latest`
With `latest` corrected, the droplet rollback is just a normal re-deploy — pull
`latest` and restart. `up -d` recreates the container in place from the newly
re-pointed image; no compose edits, no `down` needed.

```bash
ssh cassandrahq.com "docker pull ghcr.io/cassandra/ucfp:latest"
ssh cassandrahq.com "cd /opt/ucfp && docker-compose up -d"
```

### 4. Verify (do not skip)
Check each of these before you consider the site restored:

```bash
# Container is up and healthy
ssh cassandrahq.com "docker ps --filter name=ucfp --format '{{.Image}}\t{{.Status}}'"

# Site responds
curl -I https://landfall.cassandrahq.com

# Health endpoint reports the GOOD version (not the bad one)
curl https://landfall.cassandrahq.com/health

# No startup errors / migration failures in the logs
ssh cassandrahq.com "cd /opt/ucfp && docker-compose logs --tail=50 ucfp"
```

Then **exercise the flow that was broken** in a browser to confirm the rollback
actually fixed it. If `/health` still shows the bad version, the container did not
recreate from the new image — re-run the pull in step 3 (Docker may have served a
cached `latest`) and `docker-compose up -d` again.

> **If you cannot wait for the workflow.** Step 2 is a GitHub Actions round-trip (a
> couple of minutes). If the live site is hard-down and every minute counts, run the
> good image on the droplet directly as a stopgap —
> `ssh cassandrahq.com "cd /opt/ucfp && UCFP_VERSION=<GOOD> docker-compose up -d"` —
> then **still complete steps 2–3** so `latest` is correct and the droplet returns
> to tracking it. Do not leave the droplet pinned to a specific version.

---

## Migrations & data — what re-pointing the image cannot undo

The container runs migrations from its entrypoint on start. Rolling the **image**
back does **not** roll the **database** back: any migration the bad release applied
is still applied, and the older image may not expect it.

- If the bad release **only changed code** (no migration), the rollback fully
  restores the prior behavior. This is the common case.
- If the bad release **added a migration**, the older image may error on start or
  misbehave against the newer schema. Watch the step-4 logs closely.
- If a migration **destroyed or corrupted data**, re-pointing the image cannot
  recover it. Restore from the **nightly MySQL S3 backup** (`do-ucfp-backup.sh`,
  03:30 slot — see [Droplet Setup](../project/droplet-setup.md)). Because the
  pre-release phase keeps schema flexible and holds no data we are unwilling to
  discard, prefer getting the schema right before release over building rollback
  tooling for it now.

When a rollback needs a database restore, treat it as an incident: restore the
backup, then re-deploy the matching image, and verify against the restored data.

---

## Post-rollback follow-up

### Immediately (within the hour)
- [ ] Confirm the live site is healthy on the good version (step 4).
- [ ] Confirm `latest` now resolves to the good image (self-host `update.sh` is
      protected).
- [ ] Communicate the incident (Discussions / external channels).

### Short term (within 24 hours)
- [ ] Investigate the root cause in the bad release.
- [ ] Open / start the fix branch off `staging`.

### Medium term (within a week)
- [ ] Implement and thoroughly test the fix, with a regression test.
- [ ] Cut a patched release and deploy it ([Release Process](release-process.md)).
      The new release re-points `latest` forward again — nothing to un-do from this
      rollback.
- [ ] Write a post-mortem for major incidents.

## Related Documentation
- Release procedures: [Release Process](release-process.md)
- Droplet one-time setup: [Droplet Setup](../project/droplet-setup.md)
- Workflow guidelines: [Workflow Guidelines](workflow-guidelines.md)
