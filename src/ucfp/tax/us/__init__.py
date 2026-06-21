"""The US federal tax implementation -- the one place US specifics belong (`FilingStatus`,
brackets, 401(k)/IRA, RMDs, the early-withdrawal penalty).

`USFederalTaxEngine` supplies the rules; `parameters.py` holds the 2025 baseline values
that `TaxLaw` projects forward -- inflation-indexed figures scale by a COLA while
statutorily fixed thresholds stay put. Kept behind the neutral `tax/` interface; see
`ucfp/FORECAST_ENGINE.md`.
"""
