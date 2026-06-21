# Forecast Engine — Design Principles

Cross-cutting principles for the forecasting engine subsystem: the packages
**`accounts/`, `forecast/`, `period/`, `tax/`**. Boundaries no single package owns
live here; type- and package-local rules live in the relevant docstring and are
only pointed to from here. Not API docs; not process (see `docs/dev/`). Each
principle names where it is enforced — if a change breaks one, update this line in
the same change.

Flow: `ForecastParameters → Forecast → PeriodParameters → Period → books + Notices`,
with `Forecast → TaxLaw.engine_for(year) → TaxEngine`.

## Actors
- **`accounts/`** — double-entry ledger. `BooksOfAccount` aggregate, mutated only via `Bookkeeper`, read via `Chart` (structure) / `Ledger` (balances).
- **`forecast/`** — walks the time frame; resolves planner inputs into a per-interval `PeriodParameters`; threads state. **Owns all time math.**
- **`period/`** — computes one interval (accrue → settle/fund → close) against the running books. **No time math.**
- **`tax/`** — agnostic `TaxEngine` interface (`tax/us/` = US federal); `TaxLaw` yields the year's engine. Treated as a black box.

## Responsibility boundaries
- **Forecast owns time; Period is myopic.** Forecast compounds rates, prorates flows, applies indexing; Period consumes resolved values only. → `forecast/forecast.py` vs `period/period.py`
- **Engine reads facts, returns instructions; Period executes.** Engine reads book facts through the read-only `FiscalWindow` and returns charges / forced transactions / penalties; it never mutates books. → `tax/engine.py`, `period/fiscal_window.py`, `period/period.py`
- **Tax law owns rules; Forecast owns mechanics + non-ledger facts** (ages, property attrs prepared in `tax_context`). → `tax/us/engine.py` vs `forecast/forecast.py` (`_tax_context_for`)
- **Tax law does not leak.** Neutral `tax/` stays jurisdiction-agnostic (opaque state/context typed `object`); US specifics stay in `tax/us/`; the Forecast maps its vocabulary to neutral concepts (`ContributionSource`→`ContributionKind`); `TaxLaw` is the only importer of `tax/us`. → `tax/engine.py`, `tax/law.py`
- **One writer.** `Bookkeeper` is the sole mutator (record/post/realize/build); everyone else reads via `Chart` / `Ledger` / `FiscalWindow`. → `accounts/bookkeeper.py`

## Invariants
- **Balanced from t0.** Every transaction balances; a seed opening transaction balances the books from the start. → `forecast/forecast.py` (`_seed_opening_balances`)
- **Zero-basis pre-tax money** *(load-bearing).* Pre-tax/Roth holdings seed cost 0 with value in a valuation companion, so a realization taxes the whole withdrawal; taxable holdings post to cost, so only the gain is taxed. → `accounts/bookkeeper.py` (`realize`), `accounts/chart.py` (`valuation_of`)
- **Identity by handle, not name.** `handle` = own identity, `owner_handle` = subject reference; compared by `str()`. → `accounts/schemas.py`, `accounts/books.py`
- **Memo records; Notice flags.** `Transaction.description` is the record; a `Notice` is what to attend to. They never duplicate.

## Inclusion / granularity criteria
- **A Notice = unrequested *and* consequential.** Requested inputs get a memo, not a Notice. `INFO` = automatic consequential action (RMD, funding draw); `WARNING` = adverse/constraint outcome (penalty, shortfall, depletion, capped contribution). Transactional notices link by `transaction_uuid`; state notices don't. → `period/results.py` (`Notice`/`NoticeKind`)
- **A separate Account =** one per income/expense tax-class, *except where identity matters* — per-worker `WAGES` (per-worker SS cap), per-item expenses, per-loan. Lines name the account when several share a class. → `accounts/chart.py`, `period/parameters.py`

## Temporal & granularity
- **POV instants:** growth at period start; flows/events at the midpoint; tax at the tax-year close. → `period/period.py`
- **Levels vs flows:** flows prorate by `year_fraction`; levels (cash band, limits) don't; inflation/COLA applied per *year*, shared by all its sub-periods. → `forecast/forecast.py`
- **Granularity-invariant:** the same parameters run at any interval length.
- **Annual work is gated by `_is_close_of_tax_year()`, not the window's presence** — the `FiscalWindow` always exists (year-to-date, = full year at the close). Annual rules (RMD, contribution limits) read year-to-date totals from the books, so they're correct at any granularity. → `period/period.py`, `period/fiscal_window.py`

## Tax projection
- **`engine_for(year)` projects the 2025 baseline.** Inflation-indexed figures scale by a COLA; statutorily fixed thresholds (SS taxability, NIIT, capital-loss cap, §121, SALT, passive-activity allowance) stay put — their erosion is *deliberate*, not an omission. Smooth scaling, no statutory rounding. → `tax/us/parameters.py` (`*.indexed`), `tax/brackets.py`
- **COLA is a government-behaviour assumption** (`TaxProjection`), set once, held constant. → `tax/law.py`

## Cash & funding
- **Cash band:** draw the waterfall to the floor *before* settling tax (so realized income is taxed same period); sweep surplus above the ceiling *after* settlement (a basis-establishing purchase, not taxable). Tax may pull cash negative; only net worth ≤ 0 ends the forecast. → `period/period.py` (`_settle_and_fund`), `period/parameters.py` (`FundingPolicy`)
- **Cumulative rounding** apportions weighted money — each portion is the rise in the running quantized target (non-negative, sums exactly). → `period/period.py` (`_sweep_to_ceiling`)

## Where things are documented
| Scope | Home |
|---|---|
| Cross-cutting boundaries & invariants | **this file** |
| A package's responsibility & invariants | that package's `__init__.py` docstring |
| A criterion governing one type | that type's class docstring |
| Workflow, standards, testing, commenting | `docs/dev/` |
| Phase-specific (transient) rules | `docs/dev/project/project-phase.md` |
| In-flight design specs | the relevant GitHub issue |
