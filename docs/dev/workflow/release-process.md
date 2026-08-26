# Release Process

> **Role**: Process Documentation
> **Purpose**: The recurring steps to cut a release and deploy it to the droplet

A release **promotes the latest `staging` to `master` and tags it**. `master`
holds released code only -- it is never committed to directly; every change
reaches it by merging `staging`. Publishing a GitHub Release for the tag triggers
two workflows that do the actual distribution:

- `.github/workflows/docker-publish.yml` builds the unified `deploy/Dockerfile`
  and pushes `ghcr.io/cassandra/ucfp:<version>` and `:latest` (linux/amd64 + arm64).
- `.github/workflows/release-assets.yml` attaches a source archive (`ucfp.zip`).

One image serves both deployment lanes. Self-host users get the new image on their
own via `install.sh` / `update.sh` -- publishing the release is all it takes to
ship to them. Deploying the same published image to the production droplet is the
final step of this process (step 5, a short sequence of validated commands). The
droplet's one-time host and config setup is a prerequisite done once -- see
[Droplet Setup](../project/droplet-setup.md).

## Prerequisites
- Direct repository access (maintainers).
- All target changes merged into `staging`, CI green.

## Pre-Release Verification
1. Confirm CI passes on `staging`.
2. Run the full local validation gate: `make check-release` (lint + all test
   tiers + env-drift-check). This runs the `granularity` differential suite and
   the `e2e` forecast smoke that the fast `make check` dev gate skips -- the
   release is the cadence those tiers are reserved for.
3. Review the commits/PRs since the last release.

## Release Steps

### 1. Bump the version on `staging`
The `VERSION` file at the repo root is the single source of truth. Drop any
`-dev` suffix for the release.
```bash
git checkout staging
git pull origin staging
# Edit VERSION  -> e.g. 1.4.0
# Add a CHANGELOG.md line describing the release
git add VERSION CHANGELOG.md
git commit -m "Bump version to v1.4.0"
git push origin staging
```

### 2. Merge `staging` into `master`
```bash
git checkout master
git pull origin master
git merge staging
git push origin master
```
`master` will be behind `staging` until this merge -- that is normal; the release
*is* the merge. **Never** make version edits or any other commits directly on
`master`; everything arrives via `staging`.

### 3. Create the GitHub Release
```bash
gh release create v1.4.0 --target master --title "v1.4.0" --generate-notes
```
Or via the web UI: new release, tag `v1.4.0` (new), target `master`, generate
notes, set as latest, publish.

### 4. Verify the workflows
On the Actions page, confirm both succeeded:
- **Build and Publish Docker Image** -> `ghcr.io/cassandra/ucfp:v1.4.0` and
  `:latest` exist in the registry.
- **Create Release Assets** -> `ucfp.zip` is attached to the release.

### 5. Deploy to the production droplet
With the image published, deploy it to the droplet one validated step at a time.
Prerequisite: the one-time [Droplet Setup](../project/droplet-setup.md) is done. The
examples use the `ucfp-prod` SSH alias and `/opt/ucfp` path from that setup.

1. **Convert the env file** (local) — only if `production.sh` changed:
   ```bash
   python3 deploy/droplet/docker-compose-env-convert.py \
       .private/env/production.sh .private/env/docker-compose.production.env
   ```
2. **Ship the config** and confirm it landed:
   ```bash
   scp .private/env/docker-compose.production.env  ucfp-prod:/opt/ucfp/ucfp.env
   scp .private/env/production.sh                   ucfp-prod:/opt/ucfp/ucfp.sh
   scp deploy/droplet/docker-compose.production.yml ucfp-prod:/opt/ucfp/docker-compose.yml
   ssh ucfp-prod 'ls -l /opt/ucfp'
   ```
3. **Pull the released image** on the droplet:
   ```bash
   ssh ucfp-prod "docker pull ghcr.io/cassandra/ucfp:$(cat VERSION)"
   ```
4. **Restart** with the new image. `up -d` recreates the changed container in place
   (no separate `down`, so no downtime gap); migrations and collectstatic run from
   the entrypoint on start. `UCFP_VERSION` is passed inline so the compose file pins
   the exact released image:
   ```bash
   ssh ucfp-prod "cd /opt/ucfp && UCFP_VERSION=$(cat VERSION) docker-compose up -d"
   ssh ucfp-prod 'docker ps'          # container up and healthy?
   ```
5. **Verify** the live site:
   ```bash
   curl -I https://example.com
   curl https://example.com/health    # JSON including the version you just deployed
   ```
   If anything looks wrong, see [Rollback Process](rollback-process.md).

### 6. Validate the self-host install (optional)
Confirm the published image installs cleanly for self-hosters (ideally on a clean
machine):
```bash
curl -fsSL https://raw.githubusercontent.com/cassandra/ucfp/master/install.sh | bash
```

### 7. Open the next development version on `staging`
```bash
git checkout staging
# Edit VERSION -> next anticipated version with a -dev suffix, e.g. 1.5.0-dev
git add VERSION
git commit -m "Bump version to v1.5.0-dev"
git push origin staging
```

## Post-Release
- **Refine the release notes** on the GitHub release page.
- **Monitor** Issues and Discussions for the first hours after publishing. If a
  critical problem surfaces, see [Rollback Process](rollback-process.md).
- **Registry cleanup** (periodic): on the GHCR package page, prune very old
  image versions but keep `latest`, the current stable, and enough recent
  versions to roll back to.

## Versioning (Semantic Versioning)
- **Major** (`X`): breaking changes.
- **Minor** (`Y`): new features, backward compatible.
- **Patch** (`Z`): bug fixes, backward compatible.

Development versions carry a `-dev` suffix so a working tree is never mistaken
for a released build.

## Related Documentation
- Droplet one-time setup (deploy prerequisite): [Droplet Setup](../project/droplet-setup.md)
- Workflow guidelines: [Workflow Guidelines](workflow-guidelines.md)
- Rollback procedures: [Rollback Process](rollback-process.md)
