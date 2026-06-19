"""The tax materialized view of a real-estate holding -- what the engine reads from
`TaxContext.properties`, paralleling `TaxSubject` for people.

This is NOT the general `Property` domain entity (address, full financials, etc.), which
lives outside the tax/Period layer; this carries only the tax-relevant facts. They are
not on the ledger `Account` either -- the account stays a pure financial holding (the
same boundary we kept for wages) -- so they live here, with the entity referencing its
holding, whose `asset_class` distinguishes a residence (§121) from a rental (§1250).
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.enums import RealPropertyType


@dataclass( frozen = True )
class PropertyDisposition:
    """A property sold during the fiscal year. `book_gain` is the economic gain
    (proceeds - original cost) already posted to LONG_TERM_GAINS by `realize`; the
    engine applies the §121 exclusion and adds the §1250 recapture on top of it."""

    sale_date : date
    book_gain : Decimal


@dataclass( frozen = True )
class TaxProperty:
    """A real-estate holding's tax-relevant attributes. `depreciable_basis` is the
    building portion (excludes land); zero for a personal residence (not depreciated).
    `property_type` sets the rental depreciation recovery period. `disposition` is set
    by the Scenario when the property is sold this fiscal year (else None)."""

    holding           : Account
    acquisition_date  : date
    depreciable_basis : Decimal             = Decimal( '0' )
    property_type     : RealPropertyType    = RealPropertyType.RESIDENTIAL
    disposition       : PropertyDisposition = None
