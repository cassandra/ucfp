"""The projection driver.

`Forecast` walks the time frame, resolving the planner's `ForecastParameters` into a
myopic `PeriodParameters` for each interval and threading state across them.

This package owns all time math -- compounding rates, prorating flows, applying per-year
inflation/COLA -- so the Period needs none. Flows prorate by the interval fraction; levels
(the cash band, contribution limits) do not. See `ucfp/FORECAST_ENGINE.md` for the
Forecast / Period / Tax boundaries.
"""
