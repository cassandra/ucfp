# GitHub Setup

> **Role**: Project Setup
> **Purpose**: The GitHub repository configuration this project assumes, and the one-time setup to satisfy it

The CI/CD workflows, the self-host installer, and the custom commands all make
assumptions about how the GitHub repository is configured. This is the one-time
setup checklist for a new clone/fork. Per-project identity values (owner, repo,
image path) are handled by the project's rename/adaptation step; this document
is about the GitHub *settings*.

## 1. Branch convention (`staging` default, `master` released)

The project uses a two-branch model, neither being GitHub's `main` default:

- **`staging`** -- the **default branch** and the PR target; active development,
  latest code. Feature branches fork from it.
- **`master`** -- released code only. The release process merges `staging` into
  `master` and tags it; nothing is committed to `master` directly.

**Setup:** create both branches and set the **default branch to `staging`**
(*Settings -> General -> Default branch*) -- that is what makes PRs target it.
`master` comes into being at your first release (the merge from `staging`). The
branch names are referenced in `.github/workflows/django-tests.yml`
(`branches: [master, staging]`), the `install.sh`/`update.sh` raw URLs
(`/master/`, which serve *released* code), the release/rollback flows, and the
`/pickup` `/cleanup` `/release` commands; swap them there too if you rename.

**Branch protection (your call):** add branch rulesets for `staging` and
`master` (*Settings -> Branches*) to suit how you work -- this project does not
prescribe a specific policy. Two neutral facts to keep in mind: the
`Django Tests` status check cannot be *required* until a PR has triggered it at
least once (it isn't selectable before then); and `master` must stay directly
pushable by whoever cuts releases, since the release is a `git push origin
master` merge, not a PR (see [Release Process](../workflow/release-process.md)).

## 2. GitHub Actions

Four workflows live in `.github/workflows/`:

| Workflow | Trigger | Token needs |
|----------|---------|-------------|
| `django-tests.yml` | PR to `staging` or `master` | (default read-only) |
| `docker-publish.yml` | a published Release (or manual) | `packages: write` |
| `release-assets.yml` | a published Release | `contents: write` |
| `rollback.yml` | manual dispatch | `contents: write`, `packages: write` |

**Setup:** ensure **Actions are enabled** (*Settings -> Actions -> General*). Each
workflow declares the token permissions it needs, but the repo must allow Actions
to use them -- the per-workflow `permissions:` blocks are sufficient on the
default settings; do not lock the repo to read-only-with-no-overrides.

## 3. GHCR container image (must be PUBLIC for the installer)

`docker-publish.yml` pushes the self-host image to
`ghcr.io/<owner>/ucfp:<version>` and `:latest`, and `install.sh` / `update.sh`
do an **unauthenticated** `docker pull` of it.

**Setup:**
1. The GHCR package is created the **first time a Release is published** (the
   first `docker-publish` run). It does not exist before then.
2. After that first publish, set the package **visibility to Public**
   (the package page -> *Package settings -> Change visibility*), or the one-line
   installer's pull fails for anyone but you.
3. Link the package to this repository (*Package settings -> Connect repository*)
   so it inherits access and appears on the repo page.

(Building from source -- `make docker-build` -- needs none of this; only the
registry-distributed install methods 1-2 do.)

## 4. GitHub Discussions

`.github/ISSUE_TEMPLATE/config.yaml` sets `blank_issues_enabled: false` and adds
a contact link to `https://github.com/<owner>/ucfp/discussions`.

**Setup:** enable Discussions so that link doesn't 404 -- at
`https://github.com/<owner>/<project>/settings` (the *General* page), scroll to
**Features** and check **Discussions**. If you won't use Discussions, instead
edit/remove that contact link in `config.yaml`.

## 5. Labels

- The issue templates apply standard labels (`bug`, `enhancement`, ...) -- the
  defaults GitHub ships are sufficient.
- `rollback.yml` opens a tracking issue labeled **`rollback`** and **`critical`**.
  Create those two labels before the first rollback, or the issue-creation step
  fails: go to *Issues -> Labels*, click **New label**, and add `rollback` and
  `critical` (any color/description).

## 6. Templates and reviewer

- `.github/ISSUE_TEMPLATE/*` and `.github/PULL_REQUEST_TEMPLATE.md` are picked up
  automatically by GitHub -- no setup needed.
- The PR template names **`@cassandra`** as the default reviewer. Change it to a
  user/team that exists in your org, or remove it.

## 7. Local tooling (`gh`)

Every workflow slash command (`/pickup`, `/createissue`, `/pr`, `/commit`,
`/cleanup`, `/release`) shells out to the **GitHub CLI**. Each contributor needs
`gh` installed and authenticated (`gh auth login`) with write access to the repo.

## Quick checklist

- [ ] Default branch is `staging`; `master` exists for released code
- [ ] Branch rulesets for `staging` and `master` configured to your taste (keep `master` pushable for the release merge)
- [ ] Actions enabled
- [ ] After the first Release: GHCR package set **Public** and linked to the repo
- [ ] Discussions enabled (or the `config.yaml` contact link edited/removed)
- [ ] `rollback` and `critical` labels created
- [ ] PR-template reviewer (`@cassandra`) updated to a real user/team
- [ ] Owner/repo identity (`cassandra/ucfp`) updated wherever it appears -- image path, install/update raw URLs, discussions URL, PR reviewer
- [ ] Contributors have `gh` installed and authenticated

## Related Documentation
- Droplet provisioning: [Droplet Provisioning](droplet-provisioning.md)
- Droplet deployment: [Droplet / MySQL Production Deployment](droplet-deployment.md)
- Workflow: [Workflow Guidelines](../workflow/workflow-guidelines.md)
- Releases: [Release Process](../workflow/release-process.md)
- Rollback: [Rollback Process](../workflow/rollback-process.md)
