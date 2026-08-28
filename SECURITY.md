<img src="docs/assets/logo.png" alt="Landfall" width="128">

# Security

Landfall can run in two authentication modes with different security postures. Which
one you want depends on how you use it — a private instance on your own machine, or a
shared instance with separate accounts. The `UCFP_SUPPRESS_AUTHENTICATION` setting
selects between them.

In both modes, the figures you enter are encrypted at rest (via
`UCFP_FIELD_ENCRYPTION_KEY`), so the amounts and balances in your data stay protected
even if the storage or a backup were ever exposed.

## Single-user mode (no authentication)

This is the default when you self-host (`UCFP_SUPPRESS_AUTHENTICATION=true`). Every
request is served as a single implicit user who owns one household — there is no
sign-in. It is meant for a **local, trusted machine or network** — the computer or
LAN of the person whose finances it holds — and should **not** be exposed directly to
the public Internet, since anyone who can reach it has full access. Data stays on the
host (SQLite plus media under `~/.ucfp/`).

## Multi-user mode (authenticated)

Setting `UCFP_SUPPRESS_AUTHENTICATION=false` turns on authenticated, multi-tenant
operation. This is how the hosted service at
[landfall.cassandrahq.com](https://landfall.cassandrahq.com) runs, and a self-hoster
can enable it too. In this mode:

- **Authentication is required.** Sign-in is passwordless (emailed one-time codes /
  magic links), with per-IP, per-email, and global send throttling and escalating
  verification cooldowns.
- **Data is isolated per tenant.** Every financial record is scoped to an
  `Organization`, and each request resolves the active organization only from the
  signed-in user's verified memberships, so one tenant cannot read another's data.

Anyone operating an instance in this mode is responsible for the standard hardening
around it: TLS termination, protecting the environment secrets, configuring email
(sign-in depends on it) and Redis (the abuse throttles depend on it), and deciding the
account-creation policy (self-service sign-up is open by default). See the
[Self-Hosting Guide](docs/SelfHosting.md) for how to enable and configure this mode.

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's "Report a
vulnerability" (Security → Advisories) rather than opening a public issue. Security
fixes are prioritized.
