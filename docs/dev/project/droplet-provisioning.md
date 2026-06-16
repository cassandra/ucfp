# Droplet Provisioning (Cloud Host Setup)

> **Role**: Project Setup
> **Purpose**: Stand up the cloud host that [Droplet / MySQL Production Deployment](droplet-deployment.md) deploys onto

This is the one-time, **out-of-repo** setup that happens *before*
`deploy/droplet/do-droplet-init.sh` -- creating the machine, pointing DNS at it,
and obtaining a TLS certificate. It is provider-agnostic; the concrete commands
below use **DigitalOcean** (whose term for a VM is a "droplet") via the `doctl`
CLI as a worked example. Adapt them to your provider.

Order of operations:

1. Create the host and a firewall.
2. Point DNS at it.
3. Provision the host -- `do-droplet-init.sh` ([deployment doc](droplet-deployment.md) step 2) + create the MySQL DB/user ([step 1](droplet-deployment.md)).
4. Obtain the TLS certificate.
5. Monitoring (optional).

## 1. Create the host and firewall

Size the host for everything-on-one-box: the app container, MySQL, and Redis
share the droplet, so ~2 GB RAM is a reasonable floor. Using a single host (with
nginx terminating TLS) avoids paying for a separate load balancer and managed
DB/cache.

DigitalOcean example via `doctl` (replace the `<...>` placeholders):
```bash
doctl auth init                       # one-time: paste a personal access token

# Upload your SSH public key (once); note the returned key id
doctl compute ssh-key import my-key --public-key-file ~/.ssh/id_ed25519.pub

# Create the droplet
doctl compute droplet create ucfp \
    --region nyc3 \
    --image ubuntu-24-04-x64 \
    --size s-1vcpu-2gb \
    --ssh-keys <ssh-key-id> \
    --enable-monitoring

doctl compute droplet list            # note the droplet id and public IP

# Lock SSH to your own IP; open HTTP/HTTPS to the world
doctl compute firewall create \
    --name ucfp-firewall \
    --inbound-rules "protocol:tcp,ports:22,address:<your-ip>/32 protocol:tcp,ports:80,address:0.0.0.0/0 protocol:tcp,ports:443,address:0.0.0.0/0" \
    --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0" \
    --droplet-ids <droplet-id>
```

Add a host entry to `~/.ssh/config` for convenience:
```
Host ucfp-prod
    Hostname <droplet-ip>
    User root
    IdentityFile ~/.ssh/id_ed25519
```

## 2. Point DNS at the host

Buy a domain and create **A records** pointing at the droplet's public IP:

| Type | Name | Value |
|------|------|-------|
| A | `@` | `<droplet-ip>` |
| A | `www` | `<droplet-ip>` (if you want `www` to resolve) |

If you delegate DNS to your host provider, set their nameservers at the
registrar first, then add the records in the provider console. Wait for
propagation before continuing -- TLS issuance (step 4) fails until the name
resolves to the host:
```bash
dig NS example.com        # nameservers delegated?
dig example.com           # resolves to <droplet-ip>?
```

## 3. Provision the host

Run `deploy/droplet/do-droplet-init.sh` on the fresh droplet (installs Docker,
nginx + certbot, MySQL, Redis, docker-compose) and create the MySQL database and
user. Both steps are detailed in the
[deployment doc](droplet-deployment.md) (steps 2 and 1 respectively).

## 4. Obtain the TLS certificate

The init script writes an **HTTP-only** nginx config on purpose: it lets the
ACME challenge be served and avoids the chicken-and-egg of an nginx config that
references a certificate that does not exist yet. Once DNS resolves to the host
(step 2), obtain the certificate -- `certbot --nginx` injects the HTTPS server
block into the config:
```bash
certbot --nginx -d example.com -d www.example.com \
    --expand --non-interactive --agree-tos -m admin@example.com

certbot renew --dry-run               # confirm automatic renewal works
```

Finally, tell Django about the public host: add the domain (and optionally the
raw IP) to `UCFP_EXTRA_HOST_URLS` in the production env file. The first entry
becomes `SITE_DOMAIN`, and the values feed `ALLOWED_HOSTS` and the CSP rules:
```bash
export UCFP_EXTRA_HOST_URLS="example.com <droplet-ip>"
```

## 5. Monitoring (optional)

Set host-level resource alerts so you hear about trouble before users do. On
DigitalOcean: *Manage -> Monitoring -> Create Resource Alert* against the
droplet, alerting when CPU / memory / disk utilization stays above ~70% for a
few minutes. Any equivalent host-monitoring service works.

## Further production adaptations

Two things the default template does **not** ship that a real droplet deployment
usually needs. Both are out of scope for the in-repo code -- they are pointers
for when you reach them:

- **Email via an API (not SMTP).** Some hosts block outbound SMTP (DigitalOcean
  does). Switch `EMAIL_BACKEND` to an email-API backend -- [django-anymail](https://anymail.dev/)
  supports Resend, Mailgun, SES, and others. Add `anymail` to
  `requirements/base.txt` and `INSTALLED_APPS`, supply the provider API key
  through a new env var, and add the provider's DKIM/SPF records to DNS.
- **Media on object storage.** A droplet's local disk is ephemeral across
  redeploys, so user uploads under `MEDIA_ROOT` belong in object storage
  (S3 / DigitalOcean Spaces). Use [django-storages](https://django-storages.readthedocs.io/)
  with its S3 backend: point `STORAGES["default"]` at `S3Boto3Storage` and
  supply the bucket, endpoint, region, and keys through env vars.

## Related Documentation
- Deploy onto this host: [Droplet / MySQL Production Deployment](droplet-deployment.md)
- GitHub repository configuration: [GitHub Setup](github-setup.md)
