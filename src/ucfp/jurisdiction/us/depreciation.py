"""Straight-line real-estate depreciation (US §168).

The deterministic "allowed or allowable" schedule, computed from a property's
attributes rather than tracked in the ledger -- tax basis diverges from market value,
so accumulated depreciation is not a net-worth fact. Partial years prorate by elapsed
days, not the §168 mid-month convention (a deliberate simplification).
"""
from datetime import date
from decimal import Decimal

from ucfp.accounts.enums import RealPropertyType

# Straight-line recovery periods by property type: residential rental real estate is
# 27.5 years, commercial (nonresidential) 39. Same §1250 25% recapture for both.
_RECOVERY_YEARS = {
    RealPropertyType.RESIDENTIAL : Decimal( '27.5' ),
    RealPropertyType.COMMERCIAL  : Decimal( '39' ),
}
_DAYS_PER_YEAR = Decimal( '365.25' )
_ZERO          = Decimal( '0' )


def accumulated_depreciation(
        depreciable_basis : Decimal,
        acquisition_date  : date,
        as_of_date        : date,
        property_type     : RealPropertyType ) -> Decimal:
    """Straight-line depreciation of `depreciable_basis` (the building portion,
    excluding land) accrued from acquisition to `as_of_date` over the type's recovery
    period, capped at the basis once fully depreciated. Zero before acquisition or for
    a non-depreciable (zero-basis) property such as a personal residence."""
    if depreciable_basis <= 0:
        return _ZERO
    elapsed_days = ( as_of_date - acquisition_date ).days
    if elapsed_days <= 0:
        return _ZERO
    elapsed_years = Decimal( elapsed_days ) / _DAYS_PER_YEAR
    annual        = depreciable_basis / _RECOVERY_YEARS[ property_type ]
    return min( depreciable_basis, annual * elapsed_years )


def period_depreciation(
        depreciable_basis : Decimal,
        acquisition_date  : date,
        property_type     : RealPropertyType,
        as_of_open        : date,
        as_of_close       : date ) -> Decimal:
    """Depreciation deductible across a fiscal window -- the increase in accumulated
    depreciation from `as_of_open` (the prior close) to `as_of_close` (the window end,
    or the sale date if sold mid-year). Naturally handles partial first/last years and
    the basis cap."""
    opening = accumulated_depreciation( depreciable_basis, acquisition_date, as_of_open, property_type )
    closing = accumulated_depreciation( depreciable_basis, acquisition_date, as_of_close, property_type )
    return closing - opening
