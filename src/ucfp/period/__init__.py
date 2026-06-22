"""One interval's computation.

`Period` posts an interval's transactions onto the Forecast's running books in three
phases -- accrue, settle/fund, close -- and returns the `Notice`s it raised. It is myopic:
it consumes already-resolved values and does no time math, and treats the tax engine as a
black box.

Temporal points of view: growth at period start, flows and events at the midpoint, tax at
the tax-year close (gated by `_is_close_of_tax_year`, not the fiscal window's presence --
the window always exists, year-to-date). See `ucfp/FORECAST_ENGINE.md`.
"""
