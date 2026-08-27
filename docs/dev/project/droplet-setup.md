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

## 1. Host prerequisites (via `droplet-ops`)

On the droplet, from a clone of `droplet-ops` (see its README for the detail):

- A VM with the firewall open to **22** (your IP), **80**, and **443**, sized for
  co-hosting (~2 GB RAM floor). DNS **A records** for ucfp's domain → the droplet IP
  (the apex can't be a CNAME). Optional: host resource alerts (CPU / mem / disk).
- **Fresh host only:** `./provision-host.sh` (Docker, docker-compose, nginx+certbot,
  MySQL, redis). Skip on a droplet already hosting another app.
- **Register ucfp:** `./add-app.sh ucfp <domain> <port> <redis-index> [admin-email]`
  — creates `ucfp_prod` + a least-privilege user, the nginx vhost, the TLS cert, and
  `/opt/ucfp`, and prints the generated DB password plus the exact `UCFP_APP_PORT` /
  `UCFP_REDIS_DB_INDEX` / `UCFP_DB_*` values for the production config below. A
  dedicated droplet can use the defaults (port 8000, redis index 0); the database is
  created with the `utf8mb4_unicode_ci` collation (see Notes).

If the GHCR package is private, authenticate the droplet once (a public package
needs no login):
```bash
echo <GITHUB_PAT> | docker login ghcr.io -u <github-username> --password-stdin
```

## 2. Prepare the production config

Production secrets are hand-maintained under `.private/env/` (gitignored;
`env-generate.py` deliberately refuses production). Use
[`deploy/droplet/droplet.env.example`](../../../deploy/droplet/droplet.env.example)
as the template.

- `.private/env/production.sh` -- the shell-`export` form (source of truth; also
  deployed to the droplet as `ucfp.sh` for the backup cron). Set the MySQL
  `UCFP_DB_*`, `UCFP_BUNDLED_REDIS=false`, `UCFP_SUPPRESS_AUTHENTICATION=false`,
  email, `UCFP_FIELD_ENCRYPTION_KEY`, the S3 backup bucket
  (`UCFP_BACKUP_S3_BUCKET`), and `UCFP_EXTRA_HOST_URLS=https://example.com` (its
  first entry becomes `SITE_DOMAIN` and feeds `ALLOWED_HOSTS`/CSP). On a **shared**
  droplet also set `UCFP_APP_PORT` and `UCFP_REDIS_DB_INDEX` to the port and index
  `add-app.sh` reserved (step 1) -- these keep ucfp off the other apps' host port and
  redis keyspace. On a dedicated droplet the defaults (8000, 0) apply.
- Convert it to the compose `env_file` format the deploy step ships:
  ```bash
  python3 deploy/droplet/docker-compose-env-convert.py \
      .private/env/production.sh .private/env/docker-compose.production.env
  ```

The release deploy steps reach the droplet over SSH -- a `~/.ssh/config` alias
(e.g. `ucfp-prod`) or `root@<droplet-ip>` is the host they target.

## 3. Set up backups

`deploy/droplet/do-droplet-backup.sh` (cron on the droplet) dumps MySQL to S3,
reading `UCFP_BACKUP_S3_BUCKET` from the deployed `/opt/ucfp/ucfp.sh`. One-time, on
the droplet:
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
apt install -y unzip && unzip awscliv2.zip && ./aws/install
/bin/rm -rf aws awscliv2.zip
aws configure                 # IAM key/secret with PutObject on the bucket
crontab -e                    # e.g.:  0 3 * * * /opt/ucfp/do-droplet-backup.sh
```

## Notes

- **Database collation** (`utf8mb4_unicode_ci`, the collation `add-app.sh` creates
  the database with): case- and accent-insensitive, and kept that way deliberately.
  The self-host (SQLite) lane is case-sensitive; the two lanes have disjoint
  users/data, so they are **not** made to match. Audited under issue #223 -- no
  field requires case-sensitivity: sign-in tokens are validated in Python (never a
  DB equality lookup), emails are stored lower-cased (case-insensitive identity is
  desired), and every unique text column is a UUID, an enum value, or a
  machine-minted lower-case account `handle`. Caveat: that `handle` uniqueness is
  safe only because handles are machine-minted lower-case; if they ever become
  user-entered free text (e.g. case-distinct symbols), revisit its collation.
- **Outbound SMTP** is blocked by some hosts (DigitalOcean included). Sign-in
  depends on email, so use an SMTP provider/port that works from the host.
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
- Host provisioning + per-app setup (VM, firewall, DNS, services, `add-app.sh`): the **`droplet-ops`** repo
- Deploy releases onto this host: [Release Process](../workflow/release-process.md)
- Self-host deployment: [Deployment](../../Deployment.md)
- GitHub repository configuration: [GitHub Setup](github-setup.md)
