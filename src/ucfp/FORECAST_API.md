# Forecast API — Authoring Inputs & Reading Results

How to **drive** the forecast engine: build a `ForecastParameters`, run it, read a
`ForecastResult`. Sister to `FORECAST_ENGINE.md` (which is the *internals* — how the
engine computes); this is the *surface* a caller needs. **You do not need the
Forecast/Period/Tax internals to use this API** — reach for `FORECAST_ENGINE.md` only
if a result surprises you and you need to know why.

This file is a map: it names every input, says what it is *for* and when to use it, and
states the conventions and validity rules in one place. For field-by-field detail read
the docstrings in `forecast/parameters.py`; for complete worked examples read
`forecast/tests/granularity_profiles.py` (six realistic profiles exercising nearly every
input — the canonical "by example" corpus).

```
Forecast( ForecastParameters( ... ) ).run()  ->  ForecastResult
```
→ `forecast/forecast.py` (`Forecast`), `forecast/parameters.py` (all input types)

---

## Input: `ForecastParameters`

The whole forecast is one materialized value object. Build it from these pieces (only the
first four are required; the rest default to empty/None).

### Frame (required)
- **`start_date`** — the first of any month (a mid-year start makes a partial first year).
- **`end_date`** — Dec 31 for whole years; any date leaves a trailing partial year.
- **`filing_status`** — `FilingStatus` (SINGLE, MARRIED_JOINT, …). → `jurisdiction/enums.py`
- **`statute`** — `StatuteProfile( JurisdictionType.US_FEDERAL, StatuteForecastType.CURRENT_LAW )`; the pluggable tax law + its projection (COLA). → `jurisdiction/law.py`
- **`granularity`** — a `Duration`: `Duration(1, TimeUnit.YEAR)` (default), `Duration(3, TimeUnit.MONTH)` (quarterly), `Duration(1, TimeUnit.MONTH)` (monthly). Must divide 12. → `common/recurrence.py`

### Who — `subjects : list[Subject]`
- **`Subject(name, birthdate, handle=None)`** — a person; age is derived per year. Give a `handle` when the subject owns a retirement account (the account's `owner_handle` must match it).

### Opening balance sheet
- **`assets : list[AssetParameters]`** — `AssetParameters(name, asset_class, opening_value, cost_basis, handle=None, property_attributes=None, owner_handle=None)`. The opening books are seeded from these (no separate "baseline").
  - `cost_basis` is **required, no default**: a freshly-valued holding passes `opening_value` (cost = market); a **retirement account passes `0`** (its whole value is taxable on withdrawal) and **must** carry an `owner_handle`.
  - Real estate carries `PropertyAttributes` (acquisition date, depreciable basis, type) for §121/§1250; `cost_basis` is the *original* price, not the depreciated basis.
- **`loans : list[LoanParameters]`** — `LoanParameters(name, opening_balance, interest_rate, term, interest_class=NON_DEDUCTIBLE_INTEREST, annual_extra_principal=0, handle=None, interest_handle=None)`. The engine amortizes; term must be a whole number of periods at the run granularity.

### Flows — the symmetric 2×2 (+ one-time)
Pick the shape by how the flow is *naturally known*:

| | Income | Expense |
|---|---|---|
| **Rate** — an annual magnitude, no real schedule → smoothed | `income_streams : IncomeStream` | `expense_streams : ExpenseStream` |
| **Occurrence** — a real cadence (incl. one-time) → placed | `income_items : IncomeItem` | `expense_items : ExpenseItem` |

- A **stream** is `( … , amounts )` — `amounts : Schedule[WindowedAmount]`; use `Schedule.constant( WindowedAmount( Decimal('60000') ) )` for a level amount (it may step over time). Prorated evenly across the period; granularity-invariant.
- An **item** adds a **`cadence : Cadence`** — `Recurrence( Duration(1, TimeUnit.MONTH) )` for "$X/month", `Recurrence( Duration(1, TimeUnit.YEAR) )` for a yearly bill, `Recurrence( Duration(N, TimeUnit.YEAR) )` for every-N-years (car), or `OneTime( date(...) )` for a single dated occurrence. The engine resolves `count × amount`; it falls in the years it actually recurs (never amortized).
- Income keys on a **`subject`**; expense keys on a **`name`/`handle`** (intentional).
- Amounts are **today's dollars**; the engine grows them to nominal by the class's rate (the COLA lives in the Economic Outlook). → `forecast/parameters.py`, `common/schedule.py`, `common/recurrence.py`

### Retirement contributions — `contributions : list[RetirementContribution]`
- `RetirementContribution(account, amount, source, window)` — `account` is the target holding's handle; `source : ContributionSource` (WAGE / PERSONAL / EMPLOYER). The annual limit is enforced (rejected at build if the first year is over; clamped later with a Notice).

### Scheduled events — `events : list[ScheduledEvent]` (balance-sheet moves, not P&L)
- **`ScheduledTransfer(date, source, target, amount)`** — move between holdings (no tax).
- **`ScheduledPurchase(date, asset, amount)`** — buy a holding from cash at cost.
- **`ScheduledRealization(date, holding, amount, destination=None)`** — sell / withdraw (proceeds to cash) or convert (to another holding, e.g. pre-tax → Roth).
- **`ScheduledExternalReceipt(date, amount)`** — value in (equity, untaxed). Engine primitive; no current producer.
- **`ScheduledExternalDisbursement(date, amount)`** — value out (equity); used for credit-card lump payoffs.
- Note the boundaries: Money Movement events route inflows/outflows through the P&L for visibility — a **taxable** or **tax-free** receipt is a one-time `IncomeItem` (ordinary vs. tax-free class), and a **payment** out (general, charitable, or medical) is an `ExpenseItem`, not one of these equity events. → `forecast/parameters.py`, `period/events.py`

### Cash policy — `cash_account : CashAccountParameters`
- `CashAccountParameters(cash_floor=0, cash_ceiling=None, draw_order=[], sweep_allocation=None)`. Below the floor the engine draws (realizes) from `draw_order` (a list of `AssetClass`); above the ceiling it sweeps surplus into `sweep_allocation` (an `AssetAllocation( ( (handle, weight), … ) )`, weights summing to 1). A `None` ceiling/allocation disables sweeping.

### Economy — `economic_outlook : EconomicOutlook`
- `EconomicOutlook.constant( EconomicParameters( inflation=Rate(Decimal('0.025')), wage_growth=…, stock_appreciation=…, stock_dividend=…, bond_interest=…, savings_interest=…, real_estate_appreciation=…, retirement_growth=…, pension_cola=…, social_security_cola=…, rental_increase=… ) )`. Rates are `Rate(Decimal(...))`; `EconomicOutlook()` (the default) is all zeros. → `forecast/economic_outlook.py`, `common/rate.py`

### Life events & coverage
- **`subject_removals : list[SubjectRemoval]`** — `SubjectRemoval(event_date, subject_handle)`; a spouse death drives the survivor transition (filing status, account retitling).
- **`health_coverage : Optional[SubsidizedHealthCoverage]`** — `SubsidizedHealthCoverage(window, household_size, reference_premium)` for the income-subsidized (ACA-style) premium credit.

### Advanced
- **`initial_tax_state : Optional[TaxState]`** — opening carryforwards; leave `None` for a fresh start. `label : str` — a name for the books.

---

## Conventions (stated once)

- **Today's dollars.** Every input amount is in forecast-start dollars; the engine inflates/grows it. Do not pre-inflate.
- **Cadence picks the shape.** No schedule → a *stream* (smoothed). A real schedule → an *item* with a `Recurrence` or `OneTime`. One-time is a `OneTime` cadence, never a window hack.
- **Handles pair owners to accounts.** A `Subject.handle` matches an asset's `owner_handle` (required for retirement); an asset/expense `handle` lets events reference it and lets results drill down. Handles are compared by their string form — any scheme works.
- **Tax classes you set vs the engine derives.** You set the income/expense tax class on streams/items (`IncomeTaxClass.WAGES/ORDINARY/SOCIAL_SECURITY/GROSS_RENTAL/…`, `ExpenseTaxClass.LIVING/MEDICAL/SALT/CHARITABLE/MORTGAGE_INTEREST/RENTAL_EXPENSE/…`). Asset income (interest, dividends, realized gains), tax payments, and loan interest are derived by the engine — do not author them as flows. → `accounts/enums.py`

## Validity rules (enforced at build; `ForecastParameters.__post_init__`)
- Start on the **first of a month**.
- **≤ 2 filing subjects**; **≤ 1 cash holding** (the cash hub).
- **Granularity divides 12**; each **loan term divides the granularity** evenly.
- A **retirement asset** (zero-basis class) requires `cost_basis == 0` and an `owner_handle`.
- First-year **over-limit contributions** are rejected.

---

## Output: `ForecastResult`
- **`books : BooksOfAccount`** — the complete record; every figure derives from it. Read via `Bookkeeper(result.books)` → `.ledger` (`net_worth(through=)`, `market_value`, `flows(start=, end=)`) and `.chart` (accounts, `income_account`, `expense_account`, `cash_account`). → `accounts/`
- **`steps : list[ForecastStep]`** — one per interval; each `ForecastStep(span, result)` where `result : PeriodResult` carries `notices`, `is_depleted`, `closing_tax_state`.
- **`stopped_early : bool`** — net worth depleted (or all subjects gone) before the horizon.
- **Notices** — the planning-insight stream (`Notice(kind, severity, amount, detail, transaction_uuid)`): `FUNDING_DRAW`, `REQUIRED_MINIMUM_DISTRIBUTION`, `CONTRIBUTION_CAPPED`, `CASH_SHORTFALL`, `NET_WORTH_DEPLETED`, `PARTIAL_YEAR_UNTAXED` (a partial first/last year, posted but not income-taxed; `amount`/`detail` carry the approximate income that escaped tax). Surface these to the user. → `period/results.py`

For figure extraction patterns over a run, see the harness `forecast/tests/granularity_harness.py` (`yearly_figures`, `outcome`).

---

## Pointers
- **Field detail:** `forecast/parameters.py` (rich per-type docstrings — the source of truth).
- **Worked examples:** `forecast/tests/granularity_profiles.py` (6 profiles) and the focused tests `forecast/tests/test_income.py`, `test_external_flows.py`, `test_mid_year_start.py`.
- **Internals (only if needed):** `FORECAST_ENGINE.md`.
