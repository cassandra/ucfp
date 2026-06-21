"""The double-entry ledger.

The `BooksOfAccount` aggregate and its `Account` / `Transaction` / `Entry`, mutated only
through the `Bookkeeper` (the sole writer) and read through `Chart` (structure) and
`Ledger` (balances).

Invariants this package owns: every transaction balances and the books balance from t0;
pre-tax and Roth holdings use the zero-basis representation (cost 0, value in a valuation
companion) so a later realization taxes the whole withdrawal, while taxable holdings post
to cost so only the gain is taxed; accounts are identified by `handle`, not display name.
See `ucfp/FORECAST_ENGINE.md` for how this package sits in the engine.
"""
