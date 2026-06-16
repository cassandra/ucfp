# Zzz App

A full Django project base, set up and ready to begin domain development. This
is a **template**: a new project is meant to be adaptable from
this shell with a few changes.

## About this template

This is a **personal** project template. It encodes the way I set up Django
projects — the structure, conventions, tooling, and build/deploy scaffolding I
reuse — so that starting a new one is fast: take a copy, rename a few things,
and begin domain work on a foundation that already builds, tests, lints, and
deploys.

It is public, but it is **not** a framework or a product. I maintain it for my
own use and it will change to suit my needs, with no support commitment. It is
shared in case it is useful to others — as a starting point for your own
projects, or simply as a reference for how one developer wires a Django project
end to end. If it helps, great; adapt it freely.

> **Note:** This README.md should be overwritten with your domain-specific
> content. This template file version's primary job is the checklist below
> of the running list of everything that must change to adapt this to
> a new project.

## Getting a copy (download — don't clone)

**Do not `git clone` this repository.** A clone carries *this* template's git
history and its remote — exactly what you don't want. Your project needs its own
history and its own GitHub repo, with no link back here. Instead, take a
**snapshot** of the files:

- **GitHub UI:** *Code ▸ Download ZIP* (or download a tagged release), then
  unzip it where you want the project.
- **Command line:**
  ```bash
  curl -L https://github.com/cassandra/zzz-app/archive/refs/heads/master.tar.gz | tar xz
  mv zzz-master my-project && cd my-project
  ```

You now have a clean directory with **no `.git`** — a blank slate. Make it yours
by first [*Adapting to a new project*](#adapting-to-a-new-project) below, then put it under version control with [*Set up Git and GitHub*](#set-up-git-and-github).

## Project structure

Two tiers, split by **ownership** rather than by Django layer:

- **`src/zzz/` — the project package** (the one renamable unit). Holds what
  the project *owns and declares* that is domain-specific: Django config
  (`settings/`, `urls.py`, `wsgi.py`, `asgi.py`), the site-root shell
  (`views.py`, `templates/`, `static/`), and its config/extension surface
  in `environment/` (the env-var spec, the `AppConst` client/server
  constants, the injected `ClientConfig`).  This tier grows as the project
  grows; renaming the package is row 1 below.
- **`src/<name>/` — top-level sibling apps the project *uses*.** Self-contained
  units with constant, acronym-free import paths: reusable infrastructure
  (`common`, `notify`, `testing`, `background`) and project-specific feature
  apps (`custom`, `user`). There is intentionally no `zzz.apps.*` namespace.

Rule of thumb for new code: if it expands the project's *config/declaration*
surface it lives in `src/zzz/`; if it's a self-contained app you import and use,
it's a top-level sibling.

## Adapting to a new project

This template is identified by **four independent tokens**. Keeping them few
and centralized is a design goal; adapting to a new project is mostly replacing
them.

| Token | Here | What it identifies |
|-------|------|--------------------|
| **acronym** | `zzz` / `ZZZ` | the codebase: the `src/zzz/` package, the `ZZZ_` env-var prefix, the container name, `~/.zzz`, `zzz.sqlite3`, the `constance:zzz:` prefix |
| **owner** | `cassandra` | your GitHub org/user |
| **repo / image** | `zzz-app` | the GitHub repository and the GHCR image — deliberately *descriptive* and independent of the acronym |
| **display name** | `Zzz App` | the human-facing app name (`PROJECT_NAME`, surfaced everywhere as `SITE_NAME`) |

Most of the work is a few global search-and-replaces, but **order and case
matter**, because two tokens embed the acronym `zzz`:

1. `Zzz App` → your display name  *(title-case literal — do it first)*
2. `zzz-app` → your repo/image name  *(contains `zzz`, so replace it **before** the bare acronym)*
3. `zzz` then `ZZZ` → your acronym  *(**case-sensitive**, two passes; this leaves `Zzz App` untouched)*
4. `cassandra` → your owner

(A case-*insensitive* `zzz` replace would mangle `Zzz App`; replacing the bare
acronym before `zzz-app` would turn `zzz-app` into `<acronym>-app`.)

The table below explains the **kinds** of change and where the non-mechanical
*values* hide — the version string, brand color, artwork, and landing copy
(rows 4, 7, 9, 10), which no token replace can guess. Its file lists are
**illustrative, not exhaustive**; the authoritative, self-updating checklist is
the search itself:

```bash
# In a git repo: searches every tracked file (incl. dotfiles like src/.flake8)
# and auto-skips venv/ data/ .private/ (gitignored).
git grep -l  "Zzz App"    # display name
git grep -l  "zzz-app"    # repo / image name
git grep -il zzz          # acronym  (also matches zzz-app — see ordering above)
git grep -il cassandra    # owner
```

**Caveat:** `grep -r .` and a plain `rg` *silently skip dotfiles* (e.g.
`src/.flake8`, `src/.flake8-ci`), so they under-report. Before the repo is
initialized, use `find` instead of `grep -r`:

```bash
find . -type f -not -path './venv/*' -not -path './data/*' | xargs grep -il zzz
```

Also rename the one path that carries the token in its *name* (a text replace
won't): the package directory `src/zzz/`. And note the env files under
`.private/` are not in the repo — the env scripts (`make env-build*`) generate
them with the current prefix, so regenerate rather than hand-edit.

| # | Change | Location | Notes |
|---|--------|----------|-------|
| 1 | Rename the Django config package `zzz/` → new acronym | `src/zzz/` (directory) and its references in `src/manage.py`, `src/zzz/{asgi,wsgi,urls}.py`, `src/zzz/settings/*.py`, `src/zzz/environment/apps.py`, `src/zzz/environment/context_processors.py`, `src/zzz/environment/server.py`, `src/bin/docker-start-gunicorn.sh` (the `zzz.wsgi:application` arg), `Makefile` (the `src/zzz/static` path in `test-js`) | The single largest change, and the clearest case for a global token replace: `zzz.*` import paths, `DJANGO_SETTINGS_MODULE` (e.g. `zzz.settings.development`), and `src/zzz/…` paths also appear in `.github/workflows/django-tests.yml` (`zzz.settings.ci`, `src/zzz/requirements/…`) and the `.claude/` agent/command docs. The replace catches them all. |
| 2 | `ENV_PREFIX` — shell env var prefix (`ZZZ_`) | `src/zzz/environment/server.py`; and the three places that **cannot** import the app, so they hardcode the `ZZZ_*` set: `deploy/env-generate.py`, `install.sh` (`--list-env-vars`), `local.env.example`. Also the CI env block in `.github/workflows/django-tests.yml`. | In `server.py` it's the single constant every `ZZZ_*` name is built from. The other three are independent copies (a curl-able installer and a static template can't import Python) — `make env-drift-check` verifies all four declare the same variable set, so a missed rename fails CI rather than silently drifting. Global-replace `ZZZ_` in each. |
| 3 | `PROJECT_NAME` — **display-name token** (`Zzz App`) | `src/zzz/environment/server.py` | The human-facing name, surfaced everywhere via `SITE_NAME`. Title-case `Zzz App` is *not* matched by the case-sensitive acronym replace, so change it as its own token (step 1 above). |
| 4 | Version string | `VERSION` (project root) | Generic filename (no acronym) by design; just set the value. |
| 5 | Per-deployment environment values | `.private/env/development.sh` (and other env files as added) | `DJANGO_SETTINGS_MODULE`, all `ZZZ_*` values, `DJANGO_SECRET_KEY`, superuser email/password, ports, data paths. |
| 6 | Acronym in settings string-literals | `src/zzz/settings/base.py` | The SQLite filename `zzz.sqlite3` (`DATABASES`) and the `constance:zzz:` key prefix (`CONSTANCE_DATABASE_PREFIX`) — string *values* a package rename won't catch. |
| 7 | Color palette / theme | `src/zzz/static/css/main.css` (`:root`) | The `--*-color` theme variables are copied from the source project as a starting point — restyle them to the project's brand. The rest of `main.css` (icon system, Bootstrap overrides) is general and needs no change. The brand color also appears outside CSS — see row 9. |
| 8 | Branding images & favicons | `src/zzz/static/img/app-icon-*.png`, `app-logo-*.png`; `src/zzz/static/favicon.{png,ico}`; `docs/assets/logo.png` (the markdown-badge logo) | The source project's actual artwork. Don't hand-edit each served file: maintain four high-res `zzz-*` base images (kept outside the repo) and run `dev/generate-images.sh` from their directory — it scales them to every served size and writes them in place (served names are the fixed `app-*` paths that `pages/base.html`, `manifest.json`, and the doc badges reference). The `app-logo-w-tagline-*` / `docs/assets/logo.png` outputs bake in a tagline. The brand *color* is separate — see rows 7 and 9. |
| 9 | Brand color outside CSS (`#4c5bd4`) | `src/zzz/templates/manifest.json` (`theme_color`, `background_color`); `src/zzz/templates/pages/base.html` (`<meta name="theme-color">`); `src/zzz/static/img/antinode-loading.svg`; `src/notify/templates/notify/emails/base_email_message.html` (header/title; also a `#f5b945` accent border) | The same brand color as the `main.css` palette (row 7), hardcoded in these non-CSS spots a palette change won't catch. |
| 10 | Placeholder landing copy | `src/zzz/templates/pages/home.html` (landing page); `src/zzz/templates/pages/main_default.html` (`Your tagline here.`) | Replace the placeholder home content and tagline text. |
| 11 | Docker container/image name & data home (`zzz`, `~/.zzz`) | `Makefile` (`docker-build` image tags, `docker-stop` name); `deploy/local/run_container.sh` (image/container name, `ZZZ_HOME=~/.zzz`, default host port `9666`); `deploy/local/Dockerfile` (the `/etc/supervisor/conf.d/zzz.conf` filename); `install.sh`/`update.sh` (`CONTAINER_NAME`, `ZZZ_HOME`); and, for droplet adopters only, `deploy/droplet/*` (image name, `/opt/zzz`, paths) | String values a package rename won't catch, though all share the `zzz` token (a global acronym replace covers them). The default host port `9666` is the docker mapping (container is always `8000`). **Port convention:** the dev server runs on `8xxx` and the local/deployed (docker) server on `9xxx` — here `8666` / `9666`. The `xxx` is per-project (HI used `411`); change both in lockstep when adapting. This is the "ports" entry of row 5. |
| 12 | **owner** token (`cassandra`) & **repo/image** token (`zzz-app`) | `install.sh` (`DOCKER_IMAGE` + the `update.sh` raw URL); `update.sh` (`DOCKER_IMAGE`); `docker-compose.example.yml` (`image:`); `dev/dev-setup.sh` (upstream remote); `.github/workflows/{docker-publish,rollback,release-assets}.yml` (image refs / `zzz-app.zip` archive name); `.github/ISSUE_TEMPLATE/config.yaml` (discussions URL); `.github/PULL_REQUEST_TEMPLATE.md` (`@cassandra` reviewer); `.claude/commands/{pr,release}.md` (`@cassandra` reviewer, image path, install URL) | Two distinct tokens: your GitHub org/user (`cassandra`), and the repository + GHCR image + release-archive name (`zzz-app`). `zzz-app` is intentionally descriptive and independent of the acronym; it embeds `zzz`, so replace it **before** the bare acronym (step 2 above). The `.github` workflows are the CI/CD that build & publish the GHCR image and release assets — they make methods 1–2 in *Choose your install method* work; a from-source build (method 3) uses none of it. |

The app's display name needs no entry here: the page title, the PWA `manifest.json` `name`/`short_name`/`description`, and the Apple web-app title all read `{% settings_value 'SITE_NAME' %}`, which derives from `PROJECT_NAME` (row 3).

With items 1–6 done, the shell passes `manage.py check`, and `makemigrations` + `migrate` + the `bootstrap` management command (creates the superuser) all run clean. Items 7–10 are cosmetic/branding and not required for the shell to run. Items 11–12 apply only to the containerized / registry-distributed runs (see *Choose your install method*).

## Set up Git and GitHub

Once the conversion above passes (`manage.py check`, `make check`), put the
project under version control and create its GitHub home. This is a **fresh
repository**, not a fork — there is no `upstream` remote back to the template.

**Branch model.** `staging` is the **default branch on GitHub** and the target
for all PRs — it holds the latest code. `master` holds the latest *released*
code; the [release process](docs/dev/workflow/release-process.md) promotes
`staging` to `master`. (The one-line installer pulls released code from
`master`, which is why the `install.sh`/`update.sh` raw URLs reference
`/master/`.)

The steps below use the **GitHub web UI** plus a few git commands. Comfortable on
the CLI? The `gh` equivalents (e.g. `gh repo create <owner>/<project> --source=.
--remote=origin --push`) collapse several of these — translate as you like.

1. **Initialize the local repo on `staging`.**
   ```bash
   git init -b staging
   git add -A
   git commit -m "Initial commit (from the Zzz App template)"
   ```

2. **Create an empty GitHub repo.** Log in at <https://github.com> and create a
   new repository at <https://github.com/new> — **empty** (no README, `.gitignore`,
   or license; you already have them). Note its `<owner>/<project>`.

3. **Connect the remote and push `staging`.**
   ```bash
   git remote add origin git@github.com:<owner>/<project>.git
   git config --global user.email "you@example.com"   # one-time, if not already set
   git config --global credential.helper cache        # one-time, optional
   git push -u origin staging
   ```

4. **Create and push `master`** (starts equal to `staging`; the first release
   merge advances it):
   ```bash
   git checkout -b master
   git push -u origin master
   git checkout staging
   ```

5. **Set the default branch.** At
   `https://github.com/<owner>/<project>/settings`, set **Default branch** to
   `staging`.

6. **Add branch protection.** At
   `https://github.com/<owner>/<project>/settings/branches`, add a branch ruleset
   for `staging` and one for `master`, with whatever rules suit how you work.
   (CI's `Django Tests` status check only becomes available to *require* after a
   PR has triggered it at least once.)

Then finish the one-time **repository configuration** the CI/CD and
registry-distributed installs rely on — enable Actions, make the GHCR package
public, create the `rollback`/`critical` labels, enable Discussions — in
[GitHub Setup](docs/dev/project/github-setup.md). A from-source build (install
method 3) needs none of it.

## Choose your install method

The template ships configured for **self-hosting**: SQLite, a bundled-redis
container, no external services. Pick one of these self-host methods; to deploy
to a cloud droplet with MySQL instead, see
[Droplet / MySQL Production Deployment](docs/dev/project/droplet-deployment.md).
(Build internals live under `deploy/local/`, shared docker configs under
`deploy/package/`, shared env tooling under `deploy/`.)

| Method | For | What to run / copy / change |
|--------|-----|------------------------------|
| **1. Quick self-host** | A single host, Docker only (no compose needed) | `curl -fsSL https://raw.githubusercontent.com/cassandra/zzz-app/master/install.sh \| bash` — pulls the published image, generates `~/.zzz/env/local.env` (random secret + admin password) and `~/.zzz/docker-compose.yml`, and starts a container named `zzz` on port 9666. `update.sh` updates it in place. Nothing to edit. |
| **2. Self-host via compose** | Folding ZZZ into your own compose stack | Copy `docker-compose.example.yml` → `docker-compose.yml` and `local.env.example` → `local.env`; fill the env placeholders (or `make env-build`); adjust the volume host paths; `docker compose up -d`. |
| **3. Build from source** | Developers / air-gapped self-host | `make docker-build` (builds `zzz:latest` from `deploy/local/Dockerfile`), then `make docker-run` (background) or `make docker-run-fg`. Uses `~/.zzz/env/local.env` from `make env-build` and host-mounted `~/.zzz/{database,media}`. |

All three share the same **bundled-redis** image: redis runs inside the
container, so a redeploy flushes the cache — fine for a single host. Methods 1–2
require the published GitHub Container Registry image (`ghcr.io/cassandra/zzz-app`);
until that build is set up, use method 3 to build locally (or point the compose
`image:` at `zzz:latest`). Configuring the repo to publish that image — default
branch, Actions, making the GHCR package public — is the one-time
[GitHub Setup](docs/dev/project/github-setup.md).

**Exposing to the internet?** Set `ZZZ_SECRET_URL_PREFIX_UUID` to a random UUID
in your env. It moves the admin-only entry points to `/<uuid>/admin/` and
`/<uuid>/env/` so they are not at guessable URLs; blank (the default) leaves them
at `/admin/` and `/env/`.

## Adapting for droplet / MySQL production

Self-hosting (above) is the default. To deploy to a cloud droplet with MySQL +
TLS instead — a deliberate project-wide adaptation (adopt MySQL in development
too) using the supporting files under `deploy/droplet/` — see
**[Droplet / MySQL Production Deployment](docs/dev/project/droplet-deployment.md)**.

## Optional apps

These ship with the project but are **not** enabled by default, so a project
that doesn't need them pays no cost (no tables, no migrations). Enable one by
adding it to `INSTALLED_APPS` and running `manage.py migrate`.

| App | Enable with | Provides |
|-----|-------------|----------|
| `background` | `INSTALLED_APPS += ['background']` then `migrate` | Background-process infrastructure for long-running async tasks launched at startup, incl. the `DatabaseLock` table and the `ExclusionLockContext` / `InitializationLockContext` cross-worker locks (`from background.locks import ...`). |

## Optional dependencies

Some features integrate an external package that is **not** a base requirement,
so the default project carries no dependency on it. Install the package and set
the flag to opt in; until then the feature is a silent no-op.

| Feature | Enable with | Notes |
|---------|-------------|-------|
| Datadog metrics (`common/metrics.py`) | `pip install datadog`, then set `METRICS_ENABLED = True` (optionally `DATADOG_AGENT_HOST` / `DATADOG_AGENT_PORT` / `METRICS_NAMESPACE`) | Off by default; every metric call (`increment`, `gauge`, `timed`, …) is a no-op unless both the package is installed and the flag is set. |

## Deferred / open

These are known per-project touchpoints not yet finalized:

- **`SITE_NAME`** — currently a hardcoded Python default derived from
  `PROJECT_NAME`; undecided whether to make it deploy-configurable via the
  environment instead.
