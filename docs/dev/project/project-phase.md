# Project Phase: Released — Protecting Live Data and Stability

> **Status: released, in maintenance and evolution.** The first public release is
> out. There is now real, persisted user data we are unwilling to discard, so the
> greenfield freedom is gone: schema changes require migrations, and we actively
> guard against regressions. The core model and main flows are stable; the work now
> is evolving the product *carefully* — new features, fixes, and polish — without
> breaking existing data or behavior. This document governs the project in its
> released phase and supersedes the earlier pre-release/hardening posture.

## Why this document exists

To establish the assumptions that hold *right now* — a **released** codebase with
live users and durable data — so that advice, code, and review stay aligned with
where the project actually is. The earlier greenfield latitude (destructive schema
changes, "recreate the dev DB" as a migration strategy, deferring back-compat) is
**gone**. This document heads off carrying that pre-release posture forward, while
keeping the standards that were already in force (real tests, disciplined reviews,
UI/UX polish, well-factored design).

## What this phase is

- A **released** project with real users and persisted data. The core domain model
  (the double-entry foundation, the input aggregates, the forecast engine) and the
  main user flows are **stable** — we are no longer re-litigating the fundamentals.
- Originally built from a code template, now substantially our own application.
- The work now is **careful evolution**: adding features, fixing bugs, and
  continuing UI/UX polish on a stable, live foundation — without breaking existing
  data or behavior.

## Operating directives for this phase

### Released: schema and data are now durable

- There **is** production data we are unwilling to discard. Recreating a database
  is **no longer** an acceptable migration strategy.
- **Every schema or model change ships with a proper migration.** Prefer
  forward-safe, reversible migrations; write data migrations / backfills to carry
  existing rows across a change rather than dropping or orphaning them.
- **No destructive or lossy changes without an explicit, deliberate migration path.**
  Renames, type changes, and removals must preserve existing data.
- **Back-compat matters now.** Where a change affects data written by an earlier
  release (captured runs, stored inputs, persisted outputs), preserve or migrate it;
  do not silently invalidate it.
- Because getting a shape wrong is now costly to reverse, design changes to
  persisted structures deliberately — the room to "just reshape it later" is gone.

### Guard against regressions

- Existing flows and stable behavior are a contract with live users. Changes must
  not break them; **tests protect them** and are expected to stay green.
- Add a **regression test with every bug fix** (unchanged from before, now
  non-negotiable).
- Take extra care with anything touching persisted data — captured runs, stored
  inputs, materialized projection outputs — where a regression can corrupt or
  invalidate real user data, not just misbehave transiently.

### Test as you build

- Tests written now **document and protect** real, released behavior.
- **Default: write tests** for new and changed logic. `docs/dev/testing/testing-guidelines.md`
  is fully in force — focus on high-value tests (business logic, calculations, data
  integrity, meaningful edge cases), not trivial getters or ORM internals.
- Backfill tests for critical, stable paths as you touch them; you need not stop to
  retrofit exhaustive coverage of untouched code.
- The `/review` pass (with the `test-engineer` agent) is expected before a PR.

### Favor the well-factored design over the pragmatic patch

- Per the Prime Directive, we still optimize for a well-factored design, not the
  fastest working code.
- Reworking earlier or template code to get the design right remains expected — but
  now such rework must be delivered through migrations that preserve live data, not
  by recreating the database.

### UI and UX polish are in scope

- Improving styling, layout, accessibility, and interaction quality remains
  first-class work. Use the `frontend-dev` agent and the frontend guidelines.

### Performance: measure before optimizing

- No speculative performance tuning, caching layers, or scaling work without a
  measured need. With real usage now, prefer measuring against actual traffic and
  data volumes when a performance concern arises.

## What still applies (do not relax these)

- **The Prime Directive — well-factored code — is not suspended.** A live product
  raises review scrutiny, it does not lower it.
- **Reviews and quality gates are expected.** `make check` (lint + test +
  env-drift) must pass, and the `/review` discipline (parallel expert agents,
  adversarial verification) applies before a PR.
- **Dual deployment is a first-class, present-day constraint.** This project must
  support both self-hosting and a publicly accessible cloud deployment.
  Architectural choices touching configuration, secrets, storage, authentication,
  and environment boundaries must respect both targets.
- **Coding, commenting, and workflow standards** in `docs/dev/` remain in force.

## Exit criteria (when to revisit this document)

This document reflects the **released** phase and replaces the earlier pre-release
one. Revisit it when the project's posture shifts again — for example:

- A **major version or architectural change** that deliberately breaks compatibility
  and warrants its own migration and deprecation strategy.
- A change in deployment or data-ownership model that alters the constraints above.
