<img src="docs/assets/logo.png" alt="App Logo" width="128">

# Security

This application supports two deployment modes with different security postures.

## Self-hosted (single-user, trusted network)

The default self-hosted install disables authentication
(`UCFP_SUPPRESS_AUTHENTICATION=true`): every request is served as a single implicit
user who owns one household. It is intended to be run on a **local, trusted
network** — the machine or LAN of the person whose finances it holds — not exposed
directly to the public Internet. Data stays on the host (SQLite plus media under
`~/.ucfp/`).

## Cloud / multi-tenant

The application can also run as an authenticated, multi-tenant service (the cloud
"droplet" lane, `UCFP_SUPPRESS_AUTHENTICATION=false`). In this mode:

- **Authentication is required.** Sign-in is passwordless (emailed one-time codes /
  magic links), with per-IP, per-email, and global send throttling and escalating
  verification cooldowns.
- **Data is isolated per tenant.** Every financial record is scoped to an
  `Organization`, and each request resolves the active organization only from the
  signed-in user's verified memberships, so one tenant cannot read another's data.
- **Sensitive fields are encrypted at rest** using `UCFP_FIELD_ENCRYPTION_KEY`.

Operators running the cloud mode are responsible for standard hardening around it:
TLS termination, protecting the environment secrets, configuring email (sign-in
depends on it) and Redis (the abuse throttles depend on it), and deciding the
account-creation policy (self-service sign-up is open by default). See
[docs/dev/project/droplet-setup.md](docs/dev/project/droplet-setup.md).

## Status

This is pre-release software with no production data yet. Security hardening is
ongoing as part of the push toward a first release.

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's "Report a
vulnerability" (Security → Advisories) rather than opening a public issue.
