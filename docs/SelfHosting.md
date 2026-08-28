<img src="assets/logo.png" alt="Landfall" width="128">

# Self-Hosting Guide

Run your own private instance of Landfall. Your data stays entirely on your machine
and never reaches us. One command gets you running; the [Advanced
configuration](#advanced-configuration) section covers everything beyond a
single-machine setup.

Prefer not to install anything? The free hosted version at
[landfall.cassandrahq.com](https://landfall.cassandrahq.com) runs the same software.

## How self-hosting works

By default a self-hosted instance runs in **single-user mode**: there is no sign-in,
the whole app is simply yours, and all data lives on your machine. This is the right
mode for a personal instance on your own computer or a trusted home network. If you
want multiple people to have separate, authenticated accounts, see
[Multi-user mode](#multi-user-mode) — and the [Security guide](../SECURITY.md) for
the security posture of each mode.

## Prerequisites

- **Docker** — installed and running ([Get Docker](https://docs.docker.com/get-docker/))
- **Python 3.11+** — for secure credential generation (usually pre-installed)

## Quick install

**One command gets you running in about 30 seconds:**

```shell
curl -fsSL https://raw.githubusercontent.com/cassandra/ucfp/master/install.sh | bash
```

It verifies Docker is running, creates your data directories under `~/.ucfp/`,
generates secure credentials, and downloads and starts the app.

When it finishes, open **[http://localhost:9666](http://localhost:9666)** — in the
default single-user mode you are taken straight in, with no sign-in. The installer
also prints **admin credentials**; these are for the Django admin interface at
`/admin/` (site administration), not for signing into the app. Save them somewhere
safe.

**Where your data lives:**

- Configuration: `~/.ucfp/env/local.env`
- Database: `~/.ucfp/database/`
- Uploaded media: `~/.ucfp/media/`

## Managing your installation

Manage the running app with standard Docker commands:

```shell
docker logs ucfp          # view logs (add -f to follow)
docker stop ucfp          # stop the app
docker start ucfp         # start it again
docker restart ucfp       # restart (e.g. after changing the env file)
docker ps | grep ucfp     # status / health
```

## Updating

Run the update script — it pulls the latest image and recreates the container,
preserving your data:

```shell
curl -fsSL https://raw.githubusercontent.com/cassandra/ucfp/master/update.sh | bash
```

## Changing configuration

Edit `~/.ucfp/env/local.env`, then restart the app to pick up the changes:

```shell
docker restart ucfp
```

`local.env.example` in the repository root documents the full set of available
settings.

## Removing your installation

```shell
docker stop ucfp
docker rm ucfp
```

To also remove your data and configuration (this is permanent):

```shell
rm -rf ~/.ucfp/
```

## Troubleshooting

**Can't reach it from other devices on your network?**
By default the app only accepts requests to `localhost`. To reach it from another
device, set `UCFP_EXTRA_HOST_URLS` — see [Network access](#network-access) below.
An `Invalid HTTP_HOST header` error in the logs is the tell-tale sign.

**Sign-in emails not sending (multi-user mode)?**
Passwordless sign-in depends on email delivery. Configure the `UCFP_EMAIL_*`
settings — see [Email configuration](#email-configuration).

More questions are answered in the [FAQ](FAQ.md).

---

# Advanced configuration

Everything below is optional — a default single-machine install needs none of it.

## Network access

By default the app only accepts requests addressed to `localhost`. To reach it from
another device (by IP address or hostname), edit `~/.ucfp/env/local.env` and list the
URLs you'll use, including scheme and port:

```shell
# Example: accessing via IP address and hostname
UCFP_EXTRA_HOST_URLS="http://192.168.1.100:9666 http://home-server:9666"
```

Multiple URLs are space-separated. Restart after saving (`docker restart ucfp`). If
you see `Invalid HTTP_HOST header` errors in the logs, this is the setting you need —
note it requires the full URL, not just a hostname.

## Start automatically on reboot

The container is set to restart automatically (`--restart unless-stopped`), but
Docker itself must start on boot:

- **macOS (Docker Desktop):** Settings → General → "Start Docker Desktop when you log in"
- **Linux (systemd):** `systemctl is-enabled docker`, and `sudo systemctl enable docker` if needed

## Multi-user mode

To let multiple people use one instance with separate, authenticated accounts, set:

```shell
UCFP_SUPPRESS_AUTHENTICATION=false
```

This works just like the hosted service: sign-in is required and passwordless (a
one-time code emailed to each person), so you must also configure
[email](#email-configuration). Accounts are created automatically as people visit and
add their email — there is nothing to provision by hand — and each user's data is
isolated from every other user's. See the [Security guide](../SECURITY.md) for the
full picture.

## Email configuration

Email delivery is required for multi-user sign-in codes and any service notices.
Configure it in `~/.ucfp/env/local.env`:

```shell
UCFP_EMAIL_HOST=smtp.gmail.com
UCFP_EMAIL_PORT=587
UCFP_EMAIL_HOST_USER=your-email@gmail.com
UCFP_EMAIL_HOST_PASSWORD=your-app-password
UCFP_EMAIL_USE_TLS=true
```

## External database or Redis

The standard install is self-contained — SQLite plus a Redis bundled inside the
container — and needs no external services. To use your own instead, edit
`~/.ucfp/env/local.env`:

- **External MySQL/MariaDB** — fill in all five `UCFP_DB_*` variables (`UCFP_DB_HOST`,
  `UCFP_DB_PORT`, `UCFP_DB_NAME`, `UCFP_DB_USER`, `UCFP_DB_PASSWORD`). MySQL then
  takes precedence over `UCFP_DB_PATH`, so you need not clear it. Leaving them blank
  keeps the default SQLite.
- **External Redis** — set `UCFP_BUNDLED_REDIS=false` and point `UCFP_REDIS_HOST` /
  `UCFP_REDIS_PORT` at your server. The container then does not run its own Redis.

Restart after editing (`docker restart ucfp`).

## Using docker compose directly

`install.sh` writes a compose file at `~/.ucfp/docker-compose.yml`, so you can use
compose verbs instead of the `docker …` commands above — they are equivalent:

```shell
cd ~/.ucfp
docker compose ps          # status
docker compose logs -f     # follow logs
docker compose restart     # restart
docker compose down        # stop and remove the container
docker compose up -d       # bring it back
docker compose pull && docker compose up -d   # update to latest image
```

The compose file is written whether or not `docker compose` is installed, so you can
adopt these commands later.

## Integrating into your own compose stack

To run Landfall from a compose stack you already manage, rather than via `install.sh`,
copy these reference files from the repository root into your stack:

- [`docker-compose.example.yml`](../docker-compose.example.yml) — minimal service
  definition for the published image, with volumes and env file
- [`local.env.example`](../local.env.example) — the full env-var surface with
  placeholder values and inline documentation

Fill in the placeholders in `local.env`, then start the app with your usual compose
commands.

> **Env-file format note:** docker compose's `env_file` parser is **not** the same as
> a shell-sourced env file — no `export`, no shell-style quoting, no `${VAR}`
> interpolation. `local.env.example` is already in the correct format; do not adapt a
> shell-sourced env file by hand without removing those features.
