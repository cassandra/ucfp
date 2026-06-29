"""The US federal tax implementation -- the one place US tax *law* belongs (brackets, the
parameters, the surviving-spouse filing rule, depreciation recovery periods, RMDs, the
early-withdrawal penalty).

`USFederalTaxEngine` supplies the rules and derives the US specifics (e.g. the effective filing
status) from the neutral facts in the `TaxContext`; `parameters.py` holds the 2025 baseline
values that `Statute` projects forward -- inflation-indexed figures scale by a COLA while
statutorily fixed thresholds stay put. Kept behind the neutral `jurisdiction/` interface; see
`ucfp/FORECAST_ENGINE.md`.
"""
