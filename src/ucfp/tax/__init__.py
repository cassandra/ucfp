"""The pluggable tax layer.

`tax/` is the jurisdiction-agnostic interface -- `TaxEngine` (reads book facts through a
read-only `FiscalWindow` and returns the instructions the Period executes) and `TaxLaw`
(yields the year's engine) -- and `tax/us/` is the US federal implementation.

Tax law must not leak: this neutral layer stays agnostic (opaque state and context typed
`object`), jurisdiction specifics live in the country package, and `TaxLaw` is the one
place allowed to import `tax/us`. See `ucfp/FORECAST_ENGINE.md`.
"""
