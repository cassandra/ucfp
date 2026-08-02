# Project Phase: Hardening Toward First Release

> **Status: pre-release, hardening.** The basic models and flows have converged
> into a good working system. We are now gearing up for a first release by
> *hardening* it — real tests, disciplined reviews, and UI/UX polish. It is still
> pre-release: there is no production data yet, so schema and migrations stay
> flexible until v1. This document governs the project until that first release;
> the constraints here are phase-specific and will tighten (or invert) at release.

## Why this document exists

To establish the assumptions that hold *right now* — a converged-but-unreleased
codebase moving out of rapid prototyping and into hardening — so that advice,
code, and review stay aligned with where the project actually is. It heads off two
opposite mistakes: treating this like mature, released software (premature data
migrations, back-compat shims), **and** treating it like the earlier
throwaway-prototype phase (skipping tests, deferring UI polish, reworking the core
model on a whim).

## What this phase is

- A pre-release project **approaching its first release**. The core domain model
  (the double-entry foundation, the input aggregates, the forecast engine) and the
  main user flows have **converged** — we have a good working system and are no
  longer re-litigating the fundamentals each iteration.
- Built from a code template, now substantially adapted into our own application.
  Remaining template code may still be reshaped where it serves the design.
- The work now is **hardening and completing**: filling feature gaps, tightening
  quality with tests and reviews, and raising the UI to release quality — on a
  stable foundation, not by churning the core.

## Operating directives for this phase

### Still pre-release: schema and data stay flexible

- There is **no production deployment and no data we are unwilling to discard**.
- Schema and models may still change destructively; **recreating the development
  database is an acceptable "migration strategy"** until the first release.
- Do **not** add data migrations, backfills, or compatibility shims for old data
  yet. This is the **one remaining greenfield freedom, and it ends at v1** — so
  when a change would be painful to make *after* release, prefer getting the shape
  right now rather than banking on future flexibility.

### Test as you build

- The model has settled, so tests written now **document and protect** real
  behavior rather than ossifying decisions we intend to revisit.
- **Default: write tests** for new and changed logic, and add a **regression
  test** with every bug fix. `docs/dev/testing/testing-guidelines.md` is now fully
  in force — focus on high-value tests (business logic, calculations, data
  integrity, meaningful edge cases), not trivial getters or ORM internals.
- Backfill tests for critical, stable paths as you touch them; you need not stop to
  retrofit exhaustive coverage of untouched code.
- The `/review` pass (with the `test-engineer` agent) is expected before a PR.

### Favor the well-factored design over the pragmatic patch

- Per the Prime Directive, we still optimize for a well-factored design, not the
  fastest working code.
- Reworking earlier or template code to get the design right remains expected — we
  are hardening a foundation, not papering over it.

### UI and UX polish are in scope

- Improving styling, layout, accessibility, and interaction quality is now
  first-class, release-preparation work — not a premature concern to defer. Use the
  `frontend-dev` agent and the frontend guidelines.

### Performance: still measure before optimizing

- No speculative performance tuning, caching layers, or scaling work without a
  measured need. Hardening is about correctness, tests, and UX first; performance
  work follows real measurement.

## What still applies (do not relax these)

- **The Prime Directive — well-factored code — is not suspended.** Hardening is not
  a license for sloppy structure; if anything, review scrutiny rises now.
- **Reviews and quality gates are expected.** `make check` (lint + test +
  env-drift) must pass, and the `/review` discipline (parallel expert agents,
  adversarial verification) applies before a PR.
- **Dual deployment is a first-class, present-day constraint.** This project must
  support both self-hosting and a publicly accessible cloud deployment.
  Architectural choices touching configuration, secrets, storage, authentication,
  and environment boundaries must respect both targets.
- **Coding, commenting, and workflow standards** in `docs/dev/` remain in force.

## Exit criteria (when to revisit this document)

The "core model has stabilized" and "rapid iteration" triggers have already been
met — this document reflects that transition. The remaining trigger is the release
itself. Revisit — and largely retire or invert — this file when:

- We cut the **first public release**: the schema/data-flexibility freedom ends,
  and migrations plus back-compat become real obligations.
- **Real users or persisted data** exist that we are unwilling to discard.
