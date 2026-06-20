"""Subsidized health-coverage enrollment -- a jurisdiction-neutral tax input.

The resolved, single-year fact that a household holds income-subsidized health coverage,
which a country's engine turns into its own subsidy (in the US, the ACA premium tax credit).
It lives in the neutral `tax/` layer -- only `tax/us/` names "ACA" -- so any jurisdiction's
engine can consume it. The Forecast resolves its windowed planning input into this per year.
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass( frozen = True )
class SubsidizedHealthEnrollment:
    """A household's income-subsidized health-coverage enrollment for one year. `household_size`
    is the covered tax-family size; `reference_premium` is the annual premium the subsidy is
    computed against (the US engine reads it as the ACA benchmark, the SLCSP). Enrollment-month
    proration and advance-subsidy reconciliation are deferred."""

    household_size    : int
    reference_premium : Decimal
