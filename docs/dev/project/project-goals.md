# Project Goals & Requirements

> **Status: draft, high-churn.** This is the most volatile project document. It
> captures *what* we are building and *why*. Expect frequent change. It is
> paired with [project-phase.md](project-phase.md), which captures the *how* and
> *when* constraints of the current phase.

## Problem & Purpose

A personal financial-planning tool. Today this planning is spread across several
spreadsheets that have grown unwieldy and lack good sanity-checking. The goal is
a single, robustly-modeled application that replaces them.

The distinguishing idea: planning **spans past, present, and future** at
**multiple timescales** — unlike most financial calculators, which focus on a
single horizon. Past/present actuals and future projections live in one model so
that plans can be continuously reconciled against reality.

## Domain Overview

Several planning *perspectives*, all in the financial-planning realm:

- **Retirement planning** — long-horizon future budgeting.
- **Near-term cash flow** — the next ~12 months at fine granularity.
- **Social Security timing** — comparing options to find the best claiming
  strategy.

These are different lenses over a shared core financial model (see below), at
different timescales.

## Core Model (direction)

A **double-entry bookkeeping** foundation, chosen for robustness in projecting
finances. Five top-level account types: Assets, Liabilities, Equity,
Income/Revenue, Expenses.

Settled direction:

- **Current state is a snapshot** of finances (a GNUCash export, or manual
  entry), likely modeled as an initial **"seed" opening transaction** so the
  books balance from t0.
- **Real past transactions are NOT stored here** — GNUCash remains the system of
  record for actual transaction history. We keep **historical snapshots**, not a
  past journal.
- The first work is to set down the core double-entry model. The bar: convince
  ourselves it is a good foundation for the planning variations *before*
  detailing projection, plan persistence, or distributions.

The agreed core model and the locked naming conventions
(`Account` / `Transaction` / `Entry` / `Baseline`, and the deferred
`Scenario` / `Parameters` / `Projection` / `Profile`) are captured in **GitHub
issue #1** (`[Feature] Implement the initial double-entry core data model`).
Only `Baseline` joins the immediate build alongside the double-entry primitives.

> Transient design specs live in issues, not repo docs. An in-repo model/
> architecture document is warranted only *after* implementation, in an
> appropriate (different) location.

## Primary Goals

- Replace the current planning spreadsheets with a single, well-modeled tool.
- Provide strong sanity-checking / validation that the spreadsheets lack.
- Project finances across past, present, and future at multiple timescales.
- Continuously compare plan vs. reality as actuals come in over time.

## Non-Goals / Out of Scope

- **Not** replacing or reinventing expense/transaction tracking — the user uses
  **GNUCash** for tracking past and current expenses and it does that job well.
- Instead, **integrate with / import from GNUCash** so established plans can be
  updated with reality over time, tracking how well planning and reality match.

## Target Users & Deployment Modes

- **Primary (now):** the user's own financial-planning needs.
- **Aspirational (if it turns out well):** open-source it, supporting two modes:
  - **Self-hosted** — for people who want to keep their financial data private.
  - **Public, free, hosted instance** — for people who want access without
    self-hosting.

## Key Requirements

### Functional

- Double-entry core model spanning past/present/future.
- Multiple planning perspectives (retirement, near-term cash flow, SS timing).
- GNUCash data import / integration; plan-vs-actual reconciliation.
- Validation and sanity-checking of plans.

### Non-Functional

- Multi-timescale modeling (fine-grained near term, coarse long term).
- Dual deployment (self-host + public cloud) — see project-phase.md.
- Privacy/data-ownership considerations for self-hosted users.

## Constraints & Assumptions

- GNUCash is the system of record for actual past/current transactions.

## Open Questions

_Held at high level for now (see core-data-model.md "Deferred"); not to be
detailed until the projection layer:_

- The **Monte Carlo / sweep layer** (name TBD) that generates many `Scenario`s
  over sampled/enumerated `Parameters`.
- How `Parameters` model **recurring/time-parameterized** future transactions
  across differing timescales.
- Whether a captured `Projection` stores **inputs** (recompute) or **materialized
  outputs** (immutable), and how it references its `Baseline`.
- Mechanism and direction of **GNUCash integration** (import format, frequency,
  plan-vs-baseline reconciliation).
- The `Profile` model for planning subjects (needed first for Social Security).
