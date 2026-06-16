# Project Phase: Pre-Release / Greenfield

> **Status: pre-release, greenfield.** This document governs the project until
> its first public release. Every constraint here is *phase-specific* and
> expires at release. When we cut v1, revisit this file — most of it will be
> deleted or inverted.

## Why this document exists

To establish the assumptions that hold *right now*, so that advice, code, and
review stay aligned with a brand-new codebase — and to head off well-meaning
suggestions that only make sense for mature, released software.

## What this phase is

- A brand-new project, **never released**. It is built from a code template
  that already supplies structure, conventions, and utilities.
- The template is a **starting point to adapt**, not an artifact to preserve.
  Renaming, restructuring, or deleting template code is expected and encouraged
  where it serves the design.
- The **core domain model and design are provisional** and will change
  repeatedly as we iterate.

## Operating directives for this phase

### No legacy, no back-compat

- There is **no production deployment and no existing data**.
- Do **not** propose data migrations, backfills, compatibility shims,
  deprecation paths, or version-straddling code.
- Schema, models, and APIs may change freely and destructively. A breaking
  change costs nothing here — prefer the clean change over the compatible one.
- Recreating the development database is an acceptable "migration strategy"
  during this phase.

### Favor the well-factored design over the pragmatic patch

- Per the Prime Directive, we are **not** optimizing for the fastest working
  code.
- Do not suggest "pragmatic" shortcuts justified by shipping pressure, existing
  users, or the risk of change — none of those forces exist yet.
- When the clean design requires reworking template or earlier code, rework it.

### Minimal testing, deliberately

- The core model is in flux; tests written against it now would mostly
  **ossify decisions we intend to revisit**, then be discarded.
- **Default: do not write unit tests** for domain, model, or feature code
  during this phase.
- **The one exception:** universal, domain-agnostic utility code with
  **non-trivial logic** (e.g. reusable helpers in `common/`). These are stable
  and worth testing now.
- This policy is temporary and will tighten substantially as the model settles
  and we approach release.

### Premature optimization is out of scope

- No performance tuning, caching layers, or scaling work until the design
  stabilizes and a real need is measured.

## What still applies (do not relax these)

- **The Prime Directive — well-factored code — is not suspended.** "Few tests"
  and "no legacy handling" are not licenses for sloppy structure.
- **Dual deployment is a first-class, present-day constraint.** This project
  must support both self-hosting and a publicly accessible cloud deployment.
  Architectural choices touching configuration, secrets, storage,
  authentication, and environment boundaries must respect both targets from day
  one — this is the one area where designing for the future *does* apply now.
- **Coding, commenting, and workflow standards** in `docs/dev/` remain in force.

## Exit criteria (when to revisit this document)

Revisit — and likely retire — this file when any of these become true:

- We are preparing a first public release.
- Real users or real persisted data exist that we are unwilling to discard.
- The core domain model has stabilized.
