"""The pluggable jurisdiction layer -- a jurisdiction's statutory rules: tax plus the government
benefit programs (Social Security, subsidized health).

`jurisdiction/` is the jurisdiction-agnostic part: the `TaxEngine` interface (it reads book facts
through a read-only `FiscalWindow` and returns the instructions the Period executes), `Statute`
(yields the year's engine), and the neutral concepts the engine traffics in -- the taxpayer
context (`TaxContext`/`TaxSubject`/`TaxProperty`/`PropertyDisposition`), `FilingStatus`, and
subsidized-health enrollment. `jurisdiction/us/` is the US federal implementation.

The law must not leak: forecast/period depend only on this neutral layer; US statute (brackets,
parameters, the surviving-spouse rule, recovery periods) lives in `jurisdiction/us`, and `Statute`
is the one place allowed to import it. See `ucfp/FORECAST_ENGINE.md`.
"""
