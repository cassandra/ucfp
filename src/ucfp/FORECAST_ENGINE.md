# Forecast Engine — Design Principles

Cross-cutting principles for the forecasting engine subsystem: the packages
**`accounts/`, `forecast/`, `period/`, `jurisdiction/`**. Boundaries no single package owns
live here; type- and package-local rules live in the relevant docstring and are
only pointed to from here. Not API docs (to *use* the engine — build inputs, read
results — see `FORECAST_API.md`); not process (see `docs/dev/`). Each principle names
where it is enforced — if a change breaks one, update this line in the same change.

Flow: `ForecastParameters → Forecast → PeriodParameters → Period → books + Notices`,
with `Forecast → Statute.engine_for(year) → TaxEngine`.

## Actors
- **`accounts/`** — double-entry ledger. `BooksOfAccount` aggregate, mutated only via `Bookkeeper`, read via `Chart` (structure) / `Ledger` (balances).
- **`forecast/`** — walks the time frame; resolves planner inputs into a per-interval `PeriodParameters`; threads state. **Owns all time math.**
- **`period/`** — computes one interval (accrue → settle/fund → close) against the running books. **No time math.**
- **`jurisdiction/`** — agnostic `TaxEngine` interface (`jurisdiction/us/` = US federal); `Statute` yields the year's engine. Treated as a black box.

## Responsibility boundaries
- **Forecast owns time; Period is myopic.** Forecast compounds rates, prorates flows, applies indexing; Period consumes resolved values only. → `forecast/forecast.py` vs `period/period.py`
- **Engine reads facts, returns instructions; Period executes.** Engine reads book facts through the read-only `FiscalWindow` and returns charges / forced transactions / penalties; it never mutates books. → `jurisdiction/engine.py`, `period/fiscal_window.py`, `period/period.py`
- **Tax law owns rules; Forecast owns mechanics + non-ledger facts** (ages, property attrs prepared in `tax_context`). → `jurisdiction/us/engine.py` vs `forecast/forecast.py` (`_tax_context_for`)
- **Tax law does not leak.** The neutral `jurisdiction/` layer holds the general tax *concepts* — the engine interface, the taxpayer context (`TaxContext`/`TaxSubject`/`TaxProperty`/`PropertyDisposition`), and `FilingStatus`; forecast/period import only `jurisdiction/`. US tax *law* — brackets, parameters, the surviving-spouse filing rule, recovery periods — lives in `jurisdiction/us` and is reached only through the engine: the Forecast states facts (standing filing status, a spouse death year) and the engine derives the US specifics (the effective filing status). The Forecast maps its own vocabulary to neutral concepts (`ContributionSource`→`ContributionKind`); `Statute` is the only importer of `jurisdiction/us`. → `jurisdiction/context.py`, `jurisdiction/engine.py`, `jurisdiction/law.py`
- **One writer.** `Bookkeeper` is the sole mutator (record/post/realize/build); everyone else reads via `Chart` / `Ledger` / `FiscalWindow`. → `accounts/bookkeeper.py`

## Invariants
- **Balanced from t0.** Every transaction balances; a seed opening transaction balances the books from the start. → `forecast/forecast.py` (`_seed_opening_balances`)
- **Zero-basis pre-tax money** *(load-bearing).* Pre-jurisdiction/Roth holdings seed cost 0 with value in a valuation companion, so a realization taxes the whole withdrawal; taxable holdings post to cost, so only the gain is taxed. → `accounts/bookkeeper.py` (`realize`), `accounts/chart.py` (`valuation_of`)
- **Identity by handle, not name.** `handle` = own identity, `owner_handle` = subject reference; compared by `str()`. → `accounts/schemas.py`, `accounts/books.py`
- **Memo records; Notice flags.** `Transaction.description` is the record; a `Notice` is what to attend to. They never duplicate.

## Inclusion / granularity criteria
- **A Notice = unrequested *and* consequential.** Requested inputs get a memo, not a Notice. `INFO` = automatic consequential action (RMD, funding draw); `WARNING` = adverse/constraint outcome (penalty, shortfall, depletion, capped contribution). Transactional notices link by `transaction_uuid`; state notices don't. → `period/results.py` (`Notice`/`NoticeKind`)
- **A separate Account =** one per income/expense tax-class, *except where identity matters* — per-worker `WAGES` (per-worker SS cap), per-item expenses, per-loan. Lines name the account when several share a class. → `accounts/chart.py`, `period/parameters.py`

## Temporal & granularity
- **POV instants:** growth at period start; flows/events at the midpoint; tax at the tax-year close. → `period/period.py`
- **Levels vs flows:** flows resolve per interval; levels (cash band, limits) don't; inflation/COLA applied per *year*, shared by all its sub-periods. → `forecast/forecast.py`
- **Flow shapes are symmetric across income and expense — pick by how the input is naturally known.** Each direction has two shapes plus a shared one-time form:
  - *Rate* (`IncomeStream` / `ExpenseStream`): an annual magnitude with no meaningful sub-annual schedule, a `Schedule` that may step over time — prorated evenly by `year_fraction`, so granularity-invariant. Smoothing is valid only while granularity stays coarse relative to the real cadence (we cap at monthly).
  - *Occurrence* (`IncomeItem` / `ExpenseItem` + a `Cadence`): a real cadence (monthly utility, "$5,000/month" gig income, yearly property tax, car every N years) — the engine counts occurrences in the interval (`count × amount`), so the *year total* is invariant but intra-year placement (and thus depletion timing) legitimately shifts. Count × amount is exact at every granularity; this is the more granularity-honest shape.
  - *One-time* is a `OneTime` cadence on an item (a single dated occurrence) — no window hack, no separate type.
  - Income keeps a `subject` attribution; expense keys on a category name/handle. Intentional, not an inconsistency.
  → `forecast/forecast.py` (`_income_lines_for`, `_expense_lines_for`)
- **Equity crossings are not flows.** Value entering or leaving the household with no P&L effect rides a balance-sheet event: `ScheduledExternalReceipt` (value in → credits External Receipts equity, untaxed) and its mirror `ScheduledExternalDisbursement` (value out → debits External Disbursements equity, net worth down with no expense). These stay engine primitives, but the Money Movement inputs no longer route gifts through them — for visibility a receipt is booked through the P&L (a taxable receipt → ordinary `IncomeItem`, a tax-free gift/inheritance → tax-free `IncomeItem`) and a payment out → `ExpenseItem` (general = `LIVING`, plus the deductible `CHARITABLE`/`MEDICAL` kinds). `ScheduledExternalDisbursement` remains in use for credit-card lump payoffs; `ScheduledExternalReceipt` has no current producer. → `forecast/parameters.py`, `period/events.py`
- **Granularity-invariant:** the same parameters run at any interval length. Rate flows, year-end levels, and loan amortization (loans amortize monthly at any granularity — each interval rolls up the months it spans) match to rounding; occurrence placement and draw-frequency effects on balances may drift within a year — by design, not as a defect. → `forecast/forecast.py` (`_amortize_months`)
- **The tax engine is carried every interval; only income-tax settlement is gated.** The engine's exact, non-bracket rules (RMDs, the early-withdrawal penalty, the contribution limit) read year-to-date totals from the books and apply to every year, at any granularity. Bracket-driven income tax, by contrast, settles only when the interval closes a *full* calendar year — `_settle_tax` requires both `_is_close_of_tax_year()` and `PeriodParameters.full_tax_year`. → `period/period.py`, `period/fiscal_window.py`
- **Calendar-aligned spans; mid-year starts.** `period_spans` slices each calendar year from its own start, so no interval crosses December 31 (the tax-year boundary). A forecast may begin on the *first of any month*: the first year is then partial (`[start, Dec 31]`), and an end date off December 31 leaves a trailing partial year. Income tax is assessed on whole calendar years only, so a partial year (leading or trailing) is **posted but left untaxed** — the Forecast sets `full_tax_year = False` for it (`_is_full_tax_year`) rather than running a short-period estimate. Such a year raises a `PARTIAL_YEAR_UNTAXED` notice carrying the approximate income that escaped tax (capital gains + ordinary), so the user can align the start/horizon to a full year or adjust inputs; the notice is a WARNING when there is untaxed income. → `forecast/forecast.py` (`_is_full_tax_year`, `_flag_partial_tax_year`)

## Tax projection
- **`engine_for(year)` projects the 2025 baseline.** Inflation-indexed figures scale by a COLA; statutorily fixed thresholds (SS taxability, NIIT, capital-loss cap, §121, SALT, passive-activity allowance) stay put — their erosion is *deliberate*, not an omission. Smooth scaling, no statutory rounding. → `jurisdiction/us/parameters.py` (`*.indexed`), `jurisdiction/brackets.py`
- **COLA is a government-behaviour assumption** (`StatuteProjection`), set once, held constant. → `jurisdiction/law.py`

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
