"""The pluggable tax layer.

`tax/` is the jurisdiction-agnostic part: the `TaxEngine` interface (it reads book facts
through a read-only `FiscalWindow` and returns the instructions the Period executes), `TaxLaw`
(yields the year's engine), and the general tax concepts the engine traffics in -- the taxpayer
context (`TaxContext`/`TaxSubject`/`TaxProperty`/`PropertyDisposition`), `FilingStatus`, and
subsidized-health enrollment. `tax/us/` is the US federal implementation.

Tax law must not leak: forecast/period depend only on this neutral layer; US tax law (brackets,
parameters, the surviving-spouse rule, recovery periods) lives in `tax/us`, and `TaxLaw` is the
one place allowed to import it. See `ucfp/FORECAST_ENGINE.md`.
"""
