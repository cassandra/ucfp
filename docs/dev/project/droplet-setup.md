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

## 1. Create the host and firewall

Everything runs on one box -- the app container, MySQL, and redis share the host,
so ~2 GB RAM is a reasonable floor. A single host with nginx terminating TLS avoids
paying for a separate load balancer and managed DB/cache.

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

## 3. Provision the host

Run `deploy/droplet/do-droplet-init.sh <domain> [admin-email]` on the fresh host. It
installs Docker, an nginx + certbot TLS reverse proxy, MySQL, redis, and
docker-compose, and creates `/opt/ucfp`.

Create the database and a least-privilege user:
```sql
CREATE DATABASE ucfp_prod CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER ucfp_prod_user@localhost IDENTIFIED BY 'change-me';
GRANT ALL PRIVILEGES ON ucfp_prod.* TO ucfp_prod_user@localhost;
```
The `utf8mb4_unicode_ci` collation is a deliberate, audited choice -- see the
Notes section.

If the GHCR package is private, authenticate the droplet once so it can pull the
image (a public package needs no login):
```bash
echo <GITHUB_PAT> | docker login ghcr.io -u <github-username> --password-stdin
```

## 4. Obtain the TLS certificate

`do-droplet-init.sh` writes an **HTTP-only** nginx config on purpose -- it lets the
ACME challenge be served and avoids referencing a certificate that does not exist
yet. Once DNS resolves (step 2), issue the cert; `certbot --nginx` injects the HTTPS
server block:
```bash
certbot --nginx -d example.com -d www.example.com \
    --expand --non-interactive --agree-tos -m admin@example.com
certbot renew --dry-run               # confirm automatic renewal works
```

## 5. Prepare the production config

Production secrets are hand-maintained under `.private/env/` (gitignored;
`env-generate.py` deliberately refuses production). Use
[`deploy/droplet/droplet.env.example`](../../../deploy/droplet/droplet.env.example)
as the template.

- `.private/env/production.sh` -- the shell-`export` form (source of truth; also
  deployed to the droplet as `ucfp.sh` for the backup cron). Set the MySQL
  `UCFP_DB_*`, `UCFP_BUNDLED_REDIS=false`, `UCFP_SUPPRESS_AUTHENTICATION=false`,
  email, `UCFP_FIELD_ENCRYPTION_KEY`, the S3 backup bucket
  (`UCFP_BACKUP_S3_BUCKET`), and `UCFP_EXTRA_HOST_URLS=https://example.com` (its
  first entry becomes `SITE_DOMAIN` and feeds `ALLOWED_HOSTS`/CSP).
- Convert it to the compose `env_file` format the deploy step ships:
  ```bash
  python3 deploy/droplet/docker-compose-env-convert.py \
      .private/env/production.sh .private/env/docker-compose.production.env
  ```

The release deploy steps reach the droplet over SSH -- the `ucfp-prod` alias from
step 1 (or `root@<droplet-ip>`) is the host they target.

## 6. Set up backups

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

## 7. Monitoring (optional)

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
