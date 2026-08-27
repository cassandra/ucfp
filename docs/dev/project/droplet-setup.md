# Droplet Setup (one-time)

> **Role**: Project Setup
> **Purpose**: One-time setup to stand up a cloud droplet that can receive releases

This is the one-time host and configuration setup. Once it is done, each release is
deployed to the droplet as the final step of the
[Release Process](../workflow/release-process.md) -- that recurring step is not
repeated here.

The droplet runs the same published `ghcr.io/cassandra/ucfp` image as the
self-host lane, configured through environment variables for MySQL, host redis,
real authentication, and TLS (`deploy/droplet/droplet.env.example` is the
reference surface). The steps are provider-agnostic; **DigitalOcean** (whose term
for a VM is a "droplet") via the `doctl` CLI is the worked example.

> **Host provisioning lives in the shared `droplet-ops` repo, not here.** A droplet
> may host several apps side by side (each on its own domain) sharing one host
> MySQL, redis, Docker, and nginx. That singleton host state -- installing the
> shared services, and per-app DB/user, nginx vhost, TLS cert, and port/redis-index
> assignment -- is owned by `droplet-ops` so app repos do not each carry a
> conflicting copy. This document covers only the ucfp-specific configuration; it
> defers the host and per-app plumbing to `droplet-ops` (`provision-host.sh` and
> `add-app.sh`). If ucfp is the only app on a dedicated droplet, the defaults
> (port 8000, redis index 0) apply and nothing special is needed.

## 1. Create the host and firewall

*Skip this and step 3's provisioning if you are adding ucfp to a droplet that is
already provisioned and hosting another app -- go straight to step 3's `add-app.sh`.*

Everything runs on one box -- the app container, MySQL, and redis share the host,
so ~2 GB RAM is a reasonable floor (more if co-hosting several apps). A single host
with nginx terminating TLS avoids paying for a separate load balancer and managed
DB/cache.

```bash
doctl auth init                       # one-time: paste a personal access token
doctl compute ssh-key import my-key --public-key-file ~/.ssh/id_ed25519.pub

doctl compute droplet create ucfp \
    --region nyc3 --image ubuntu-24-04-x64 --size s-1vcpu-2gb \
    --ssh-keys <ssh-key-id> --enable-monitoring
doctl compute droplet list            # note the droplet id and public IP

# Lock SSH to your own IP; open HTTP/HTTPS to the world
doctl compute firewall create --name ucfp-firewall \
    --inbound-rules "protocol:tcp,ports:22,address:<your-ip>/32 protocol:tcp,ports:80,address:0.0.0.0/0 protocol:tcp,ports:443,address:0.0.0.0/0" \
    --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0" \
    --droplet-ids <droplet-id>
```

A `~/.ssh/config` entry (`Host ucfp-prod` / `Hostname <ip>` / `User root`) makes the
later SSH-based deploy convenient.

## 2. Point DNS at the host

Create **A records** for the domain (`@`, and `www` if wanted) pointing at the
droplet's public IP. Wait for propagation before the TLS step -- certificate
issuance fails until the name resolves to the host:
```bash
dig NS example.com        # nameservers delegated?
dig example.com           # resolves to <droplet-ip>?
```

## 3. Provision the host and register ucfp

Both steps use the shared `droplet-ops` repo (clone it onto the droplet). Its
README carries the authoritative details.

**Fresh droplet only** -- install the shared services once (skip on a droplet
already hosting another app):
```bash
./provision-host.sh          # Docker, docker-compose, nginx+certbot, MySQL, redis
```

**Every droplet** -- register ucfp. This reserves ucfp's port and redis index
(rejecting collisions with any co-hosted app), creates the `ucfp_prod` database and
a least-privilege `ucfp_prod_user`, installs the nginx vhost, obtains the TLS cert
via certbot, and creates `/opt/ucfp`:
```bash
# ./add-app.sh <app> <domain> <port> <redis-index> [admin-email]
# Shared droplet, ucfp on its own subdomain (pick a free port + index from
# droplet-ops/registry.tsv; subdomains take no www, the default):
./add-app.sh ucfp ucfp.example.com 8001 1 admin@example.com
# Dedicated droplet on a bare apex domain that should also answer on www:
# ADD_APP_WWW=1 ./add-app.sh ucfp example.com 8000 0 admin@example.com
```
`add-app.sh` prints the generated DB password once and the exact
`DJANGO_SERVER_PORT` / `UCFP_REDIS_DB_INDEX` / `UCFP_DB_*` values to put in the
production env (step 4). It creates the database with the `utf8mb4_unicode_ci`
collation -- a deliberate, audited choice; see the Notes section. TLS uses an
HTTP-only vhost first so the ACME challenge can be served, then `certbot --nginx`
injects the HTTPS server block; confirm automatic renewal with
`certbot renew --dry-run`. DNS (step 2) must resolve to the host before this runs.

If the GHCR package is private, authenticate the droplet once so it can pull the
image (a public package needs no login):
```bash
echo <GITHUB_PAT> | docker login ghcr.io -u <github-username> --password-stdin
```

## 4. Prepare the production config

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
  droplet also set `DJANGO_SERVER_PORT` and `UCFP_REDIS_DB_INDEX` to the port and
  index `add-app.sh` reserved (step 3) -- these keep ucfp off the other apps' host
  port and redis keyspace. On a dedicated droplet the defaults (8000, 0) apply.
- Convert it to the compose `env_file` format the deploy step ships:
  ```bash
  python3 deploy/droplet/docker-compose-env-convert.py \
      .private/env/production.sh .private/env/docker-compose.production.env
  ```

The release deploy steps reach the droplet over SSH -- the `ucfp-prod` alias from
step 1 (or `root@<droplet-ip>`) is the host they target.

## 5. Set up backups

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

## 6. Monitoring (optional)

Set host-level resource alerts (CPU / memory / disk sustained above ~70%). On
DigitalOcean: *Manage -> Monitoring -> Create Resource Alert*. Any equivalent works.

## Notes

- **Database collation** (`utf8mb4_unicode_ci`, set in the `CREATE DATABASE`
  above): case- and accent-insensitive, and kept that way deliberately. The
  self-host (SQLite) lane is case-sensitive; the two lanes have disjoint
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
- Deploy releases onto this host: [Release Process](../workflow/release-process.md)
- Self-host deployment: [Deployment](../../Deployment.md)
- GitHub repository configuration: [GitHub Setup](github-setup.md)
