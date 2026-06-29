"""The tax materialized view of a real-estate holding -- what an engine reads from
`TaxContext.properties`.

This is NOT the general `Property` domain entity (address, full financials, etc.), which
lives outside the tax/Period layer; this carries only the tax-relevant facts. They are
not on the ledger `Account` either -- the account stays a pure financial holding -- so they
live here, with the entity referencing its holding, whose `asset_class` distinguishes a
residence from a rental.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from ucfp.accounts.books import Account
from ucfp.accounts.enums import RealPropertyType


@dataclass( frozen = True )
class PropertyDisposition:
    """A rental sold during the fiscal year, marking its `sale_date` so the engine can
    accrue depreciation recapture through that date. It carries no gain: the gain is already
    in the ledger (a residence's in its own exclusion account, a rental's in long-term gains),
    and recapture is computed from the property's depreciation attributes, not the gain. A
    residence sale needs no disposition -- its own gains account is the signal."""

    sale_date : date


@dataclass( frozen = True )
class TaxProperty:
    """A real-estate holding's tax-relevant attributes. `depreciable_basis` is the
    building portion (excludes land); zero for a personal residence (not depreciated).
    `property_type` sets the rental depreciation recovery period. `disposition` is set
    when the property is sold this fiscal year (else None)."""

    holding           : Account
    acquisition_date  : date
    depreciable_basis : Decimal             = Decimal( '0' )
    property_type     : RealPropertyType    = RealPropertyType.RESIDENTIAL
    disposition       : Optional[ PropertyDisposition ] = None
