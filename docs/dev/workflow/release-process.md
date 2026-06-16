# Release Process

> **Role**: Process Documentation
> **Purpose**: How a versioned release is cut, published, and validated

A release **promotes the latest `staging` to `master` and tags it**. `master`
holds released code only -- it is never committed to directly; every change
reaches it by merging `staging`. Publishing a GitHub Release for the tag triggers
two workflows that do the actual distribution:

- `.github/workflows/docker-publish.yml` builds `deploy/local/Dockerfile` and
  pushes `ghcr.io/cassandra/ucfp:<version>` and `:latest` (linux/amd64 + arm64).
- `.github/workflows/release-assets.yml` attaches a source archive (`ucfp.zip`).

Self-host users then get the new image via `install.sh` / `update.sh`. (The
droplet/MySQL deployment is separate -- see
[Droplet / MySQL Production Deployment](../project/droplet-deployment.md) and
`deploy/droplet/deploy-prod.sh`.)

## Prerequisites
- Direct repository access (maintainers).
- All target changes merged into `staging`, CI green.

## Pre-Release Verification
1. Confirm CI passes on `staging`.
2. Run local validation: `make check` (lint + test + env-drift-check).
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

### 5. Validate the install
Confirm the published image installs cleanly (ideally on a clean machine):
```bash
curl -fsSL https://raw.githubusercontent.com/cassandra/ucfp/master/install.sh | bash
```

### 6. Open the next development version on `staging`
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
- Workflow guidelines: [Workflow Guidelines](workflow-guidelines.md)
- Rollback procedures: [Rollback Process](rollback-process.md)
