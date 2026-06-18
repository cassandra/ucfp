"""ACA marketplace enrollment -- the per-household input the premium-tax-credit stage
reads from `TaxContext.aca`.

None when the household is not on a marketplace plan (e.g. Medicare or employer
coverage); the Profile gates this -- typically "use ACA in the pre-Medicare years".
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass( frozen = True )
class AcaEnrollment:
    """A household's ACA marketplace enrollment for the year. `benchmark_premium` is the
    annual second-lowest-cost silver plan (SLCSP) cost for the household -- specific to
    its members and location, so a per-household input rather than a national parameter.
    Enrollment-month proration and advance-PTC reconciliation are deferred."""

    household_size    : int
    benchmark_premium : Decimal
