# Droplet Setup (one-time)

> **Role**: Project Setup
> **Purpose**: One-time **ucfp-specific** configuration for deploying to a cloud droplet

The droplet runs the same published `ghcr.io/cassandra/ucfp` image as the self-host
lane, configured through environment variables for MySQL, host redis, real
authentication, and TLS (`deploy/droplet/droplet.env.example` is the reference
surface). Once this is done, each release is deployed as the final step of the
[Release Process](../workflow/release-process.md).

**Host provisioning is not covered here.** Standing up the droplet -- the VM, its
firewall, the shared MySQL / redis / Docker / nginx, and ucfp's per-app
registration (its database, nginx vhost, TLS cert, and port / redis-index
reservation) -- is done with the shared **`droplet-ops`** repo, whose README is
authoritative. A droplet can host several apps side by side this way. This document
covers only what is ucfp-specific: the production config, backups, and notes.

## Prerequisites

Provision the host and register ucfp first, with the shared **`droplet-ops`** repo
(its README and runbooks are authoritative). That registration is what supplies the
inputs step 1 needs: the **DB credentials**, and — on a shared droplet — the **host
port** and **redis index** reserved for ucfp.

If ucfp's GHCR image is private, log the droplet in once (a public image needs no
login):
```bash
echo <GITHUB_PAT> | docker login ghcr.io -u <github-username> --password-stdin
```

## 1. Prepare the production config

Production secrets are hand-maintained under `.private/env/` (gitignored;
`env-generate.py` deliberately refuses production). Use
[`deploy/droplet/droplet.env.example`](../../../deploy/droplet/droplet.env.example)
as the template.

Generate the four per-deployment secrets. Each produces **shell-safe, URL-safe**
output (no quotes, spaces, `$`, or backticks), so it drops into the `export` form
without escaping:

```bash
# UCFP_FIELD_ENCRYPTION_KEY -- Fernet key: 32 random bytes, url-safe base64
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode('ascii'))"

# DJANGO_SECRET_KEY -- 50 url-safe chars
python3 -c "import secrets; print(secrets.token_urlsafe(50)[:50])"

# DJANGO_SUPERUSER_PASSWORD -- the /admin login (~22 url-safe chars)
python3 -c "import secrets; print(secrets.token_urlsafe(16))"

# UCFP_SECRET_URL_PREFIX_UUID -- opaque path segment hiding /admin/ and /env/
python3 -c "from uuid import uuid4; print(uuid4().hex)"
```

Two values are **not** generated here -- carry them over: `UCFP_DB_PASSWORD` (printed
by the add-app step above) and `UCFP_EMAIL_API_KEY` (the Resend key from the email
setup). The rest (`DJANGO_SUPERUSER_EMAIL`, the from-address, `UCFP_EXTRA_HOST_URLS`)
are chosen values, not secrets.

- `.private/env/production.sh` -- the shell-`export` form (source of truth; also
  deployed to the droplet as `ucfp.sh` for the backup cron). Set the MySQL
  `UCFP_DB_*`, `UCFP_BUNDLED_REDIS=false`, `UCFP_SUPPRESS_AUTHENTICATION=false`,
  email, `UCFP_FIELD_ENCRYPTION_KEY`, and `UCFP_EXTRA_HOST_URLS=https://example.com` (its
  first entry becomes `SITE_DOMAIN` and feeds `ALLOWED_HOSTS`/CSP). On a **shared**
  droplet also set `UCFP_APP_PORT` and `UCFP_REDIS_DB_INDEX` to the port and index
  the add-app runbook reserved (see Prerequisites) -- these keep ucfp off the other apps' host port and
  redis keyspace. On a dedicated droplet the defaults (8000, 0) apply.
- Convert it to the compose `env_file` format the deploy step ships:
  ```bash
  python3 deploy/droplet/docker-compose-env-convert.py \
      .private/env/production.sh .private/env/docker-compose.production.env
  ```

The release deploy steps reach the droplet over SSH -- a `~/.ssh/config` alias
(e.g. `ucfp-prod`) or `root@<droplet-ip>` is the host they target.

## 2. Set up backups

ucfp's `deploy/droplet/do-ucfp-backup.sh` (deployed to `/opt/ucfp`) dumps MySQL to
S3 — the bucket/prefix are set in the script, and it reads the `UCFP_DB_*` credentials
from the deployed `/opt/ucfp/ucfp.sh`. It relies on the droplet's shared **AWS CLI + S3
credentials** — a host-level, once-per-droplet setup done via droplet-ops'
`runbooks/setup-backups.md`. With that in place, schedule ucfp's job at its registry
backup slot (**03:30** -- staggered so co-hosted apps don't dump concurrently):

```bash
scp deploy/droplet/do-ucfp-backup.sh cassandrahq.com:/tmp/do-ucfp-backup.sh
```

```bash
ssh cassandrahq.com
sudo cp /tmp/do-ucfp-backup.sh /opt/ucfp/do-ucfp-backup.sh
crontab -e                    # ucfp's 03:30 registry slot:  30 3 * * * /opt/ucfp/do-ucfp-backup.sh
```

## Notes

- **Database collation** (`utf8mb4_unicode_ci`, the collation the add-app runbook
  creates the database with): case- and accent-insensitive, and kept that way deliberately.
  The self-host (SQLite) lane is case-sensitive; the two lanes have disjoint
  users/data, so they are **not** made to match. Audited under issue #223 -- no
  field requires case-sensitivity: sign-in tokens are validated in Python (never a
  DB equality lookup), emails are stored lower-cased (case-insensitive identity is
  desired), and every unique text column is a UUID, an enum value, or a
  machine-minted lower-case account `handle`. Caveat: that `handle` uniqueness is
  safe only because handles are machine-minted lower-case; if they ever become
  user-entered free text (e.g. case-distinct symbols), revisit its collation.
- **Outbound SMTP** is blocked by some hosts (DigitalOcean included), so the cloud
  lane (`ucfp.settings.production`) sends email through **Resend's HTTP API** via
  Anymail, not SMTP -- driven by `UCFP_EMAIL_API_KEY` and a verified sender. Sign-in
  depends on email, so both must be set (see the droplet-ops `setup-email` runbook).
- **Testing against MySQL**: dev and CI default to SQLite. Because SQLite and MySQL
  differ subtly, run the suite against a local MySQL before a release that touches
  models or migrations (point the same `UCFP_DB_*` at a local MySQL). On macOS,
  `pip install mysqlclient` often needs the client libs pointed out first:
  ```bash
  export MYSQLCLIENT_CFLAGS="-I/usr/local/mysql/include"
  export MYSQLCLIENT_LDFLAGS="-L/usr/local/mysql/lib -lmysqlclient -Wl,-rpath,/usr/local/mysql/lib"
  pip install mysqlclient==2.2.7 --no-cache-dir
  ```

## Related Documentation
- Host provisioning + per-app setup (VM, firewall, DNS, services, the add-app runbook): the **`droplet-ops`** repo
- Deploy releases onto this host: [Release Process](../workflow/release-process.md)
- Self-host deployment: [Deployment](../../Deployment.md)
- GitHub repository configuration: [GitHub Setup](github-setup.md)
