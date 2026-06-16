# Droplet / MySQL Production Deployment

> **Role**: Project Setup
> **Purpose**: Convert the self-hosting default to a cloud droplet running MySQL + TLS

Self-hosting (SQLite + a bundled-redis container) is the default. A cloud droplet serving real
traffic wants a multi-writer database (MySQL, not single-writer SQLite) and TLS.
That is a deliberate **project-wide** adaptation, not a runtime toggle -- adopt
MySQL in development too, so dev and production behave the same. The
`deploy/droplet/` directory holds the supporting files; the steps:

1. **Switch the database to MySQL** -- edit `DATABASES` in
   `src/ucfp/settings/base.py` (a commented MySQL form is right there), add the
   `DATABASE_*` rows to `_ENV_SPEC` in `src/ucfp/environment/server.py` (so they
   are read through `ENV`), and add `mysqlclient==2.2.7` to
   `src/ucfp/requirements/base.txt`. Set `UCFP_DB_HOST/PORT/NAME/USER/PASSWORD`
   in your env files. (Once they are in `_ENV_SPEC`, `make env-drift-check` will
   expect them in the generated env files too -- add them there as well.)

   Create the database and a least-privilege user (run once per MySQL
   instance -- the same shape works for a dev machine and for the droplet):
   ```sql
   CREATE DATABASE ucfp      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   -- Django's test runner creates and drops `test_<NAME>`, so grant it too:
   CREATE DATABASE test_ucfp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER ucfp_user@localhost IDENTIFIED BY 'change-me';
   GRANT ALL PRIVILEGES ON ucfp.*      TO ucfp_user@localhost;
   GRANT ALL PRIVILEGES ON test_ucfp.* TO ucfp_user@localhost;
   ```
   On **macOS**, `pip install mysqlclient` often cannot find the client libs;
   point it at the Homebrew/installer MySQL before installing:
   ```bash
   export MYSQLCLIENT_CFLAGS="-I/usr/local/mysql/include"
   export MYSQLCLIENT_LDFLAGS="-L/usr/local/mysql/lib -lmysqlclient -Wl,-rpath,/usr/local/mysql/lib"
   pip install mysqlclient==2.2.7 --no-cache-dir
   ```
2. **Provision the droplet once** -- run `deploy/droplet/do-droplet-init.sh` on a
   fresh host (set `DOMAIN` first). It installs Docker, an nginx + certbot TLS
   reverse proxy, MySQL, Redis, and docker-compose, and creates `/opt/ucfp`. The
   nginx config is written HTTP-only; `certbot --nginx` (run after DNS points at
   the host) obtains the certificate and injects the HTTPS server block.
3. **Build and ship the image** -- build the `ucfp` image from the droplet
   Dockerfile (MySQL client libs, no bundled redis) and save it, then run the
   deploy script (set `DEPLOY_HOST` in it first):
   ```
   docker build -f deploy/droplet/Dockerfile --platform linux/amd64 \
       -t ucfp:$(cat VERSION) -t ucfp:latest .
   docker save ucfp:$(cat VERSION) | gzip > /tmp/ucfp-docker-image-$(cat VERSION).tar.gz
   ./deploy/droplet/deploy-prod.sh   # scp image + compose + env, docker load, compose up
   ```
   The image keeps the name `ucfp` (a project uses one method, not both). If you
   want `make docker-build` to build this image instead of the self-host one,
   repoint it at `deploy/droplet/Dockerfile`.
4. **Backups** -- `deploy/droplet/do-droplet-backup.sh` (cron on the droplet)
   dumps MySQL to S3; set `S3_BUCKET`. One-time, on the droplet: install the AWS
   CLI, configure credentials, and add the cron entry.
   ```bash
   curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
   apt install -y unzip && unzip awscliv2.zip && ./aws/install
   /bin/rm -rf aws awscliv2.zip
   aws configure                 # paste the IAM key/secret with PutObject on S3_BUCKET
   aws sts get-caller-identity   # verify
   crontab -e                    # add, e.g.:  0 3 * * * /root/do-droplet-backup.sh
   ```

`deploy/droplet/docker-compose-env-convert.py` converts a shell `production.sh`
env file into the compose `.env` format `deploy-prod.sh` ships. The per-project
values in these files (domain, `DEPLOY_HOST`, S3 bucket, DB credentials) are
per-project values you set when standing up your own deployment.

## Related Documentation
- Stand up the host first: [Droplet Provisioning](droplet-provisioning.md)
- GitHub repository configuration: [GitHub Setup](github-setup.md)
- Release process: [Release Process](../workflow/release-process.md)
