"""Derived income figures from an assessment -- AGI and the modified-AGI variants.

"MAGI" is not one number: it is AGI plus a program-specific set of add-backs. So this
holds AGI and the individual add-back components, and exposes each program's MAGI as a
property -- consumers never re-derive which add-backs apply. The engine uses `niit_magi`
internally; the ACA premium-tax-credit stage uses `aca_magi`; the Scenario's IRMAA
surcharge uses `irmaa_magi`.

Surfaced on `TaxAssessment.figures` so downstream consumers (IRMAA, effective net
worth) can read the assessment's MAGI without re-running the income pipeline.
"""
from dataclasses import dataclass
from decimal import Decimal

from ucfp.jurisdiction.engine import TaxFigures as NeutralTaxFigures


@dataclass( frozen = True )
class TaxFigures( NeutralTaxFigures ):
    """AGI and the MAGI add-back components for one assessment -- the US realization of the
    neutral `TaxFigures` marker. `untaxed_social_security` is the portion of benefits excluded
    from AGI (gross minus the taxable part)."""

    agi                     : Decimal
    tax_exempt_interest     : Decimal
    untaxed_social_security : Decimal

    @property
    def niit_magi( self ) -> Decimal:
        """MAGI for the Net Investment Income Tax: AGI plus the foreign-earned-income
        exclusion (not modeled -> zero), so AGI."""
        return self.agi

    @property
    def aca_magi( self ) -> Decimal:
        """MAGI for the ACA premium tax credit: AGI plus tax-exempt interest, the
        untaxed portion of Social Security, and the foreign exclusion (not modeled)."""
        return self.agi + self.tax_exempt_interest + self.untaxed_social_security

    @property
    def irmaa_magi( self ) -> Decimal:
        """MAGI for Medicare IRMAA: AGI plus tax-exempt interest (no Social Security
        add-back). Surfaced for the Scenario's lagged-MAGI surcharge."""
        return self.agi + self.tax_exempt_interest
