# Project Goals & Requirements

> **Status: stabilizing.** The core model and main flows have converged, so this
> is far less volatile than it was, though it still evolves as features are added.
> It captures *what* we are building and *why*, and is paired with
> [project-phase.md](project-phase.md), which captures the *how* and *when*
> constraints of the current (hardening) phase.

## Problem & Purpose

A personal financial-planning tool. Today this planning is spread across several
spreadsheets that have grown unwieldy and lack good sanity-checking. The goal is
a single, robustly-modeled application that replaces them.

## Domain Overview

Several planning *perspectives*, all in the financial-planning realm:

- **Retirement planning** — long-horizon future budgeting.
- **Near-term cash flow** — the next ~12 months at fine granularity.
- **Social Security timing** — comparing options to find the best claiming
  strategy.

These are different lenses over a shared core financial model (see below), at
different timescales.

## Core Model (implemented)

A **double-entry bookkeeping** foundation, chosen for robustness in projecting
finances. Five top-level account types: Assets, Liabilities, Equity,
Income/Revenue, Expenses. The core primitives and the projection layer are now
**built and stable**: the double-entry `Account` / `Transaction` / `Entry` model,
the `Baseline`, the input aggregates (`Profile` / `Plans` / `Assumptions`), the
forecast engine, and captured projection runs.

Settled model decisions:

- **Current state is a snapshot** of finances (manual entry, possible future import),
  modeled as an initial **opening transaction** so the books balance from t0.
- **Real past transactions are NOT stored here** — actual transaction history.
  We keep **historical snapshots**, not a past journal.
- A captured run stores **materialized outputs** (an immutable projection), not
  merely its inputs.

> Transient design specs live in issues, not repo docs. An in-repo model/
> architecture document is warranted once the design merits one, in an appropriate
> location distinct from these transient project docs.

## Primary Goals

- Replace the current planning spreadsheets with a single, well-modeled tool.
- Provide strong sanity-checking / validation that the spreadsheets lack.
- Project finances across to future at multiple timescales.
- Continuously compare plan vs. reality as actuals come in over time.

## Non-Goals / Out of Scope

- **Not** replacing or reinventing expense/transaction tracking — the user uses

## Target Users & Deployment Modes

- **Primary (now):** the user's own financial-planning needs.
- **Aspirational:** release it publicly as free,
  source-available software (free for noncommercial use under the PolyForm
  Noncommercial License; commercial use by separate license), supporting two modes:
  - **Self-hosted** — for people who want to keep their financial data private.
  - **Public, free, hosted instance** — for people who want access without
    self-hosting.

## Key Requirements

### Functional

- Double-entry core model spanning past/present/future.
- Multiple planning perspectives (retirement, near-term cash flow, SS timing).
- Validation and sanity-checking of plans.

### Non-Functional

- Multi-timescale modeling (fine-grained near term, coarse long term).
- Dual deployment (self-host + public cloud) — see project-phase.md.
- Privacy/data-ownership considerations for self-hosted users.
