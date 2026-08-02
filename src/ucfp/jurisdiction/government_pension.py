"""Government pension (social-insurance retirement benefit) -- the jurisdiction-neutral layer.

A jurisdiction provides a state retirement benefit whose realized amount depends on when it is
claimed relative to that jurisdiction's normal retirement age. `GovernmentPension` is the
composition point that maps a jurisdiction (`JurisdictionType`) to its concrete claiming-age schedule
(`jurisdiction.us` for US Social Security today), so a caller asks for a realized benefit without
encoding which jurisdiction's rules apply -- the same shape as `Statute` for the tax engine.

It lives in `jurisdiction` because it is jurisdiction-statutory, the same family as the tax law. The
jurisdiction is keyed on `JurisdictionType` for now (the existing jurisdiction discriminator); when
`jurisdiction/` generalizes beyond tax, that becomes a first-class jurisdiction concept.
"""
from datetime import date
from decimal import Decimal

from ucfp.accounts.enums import IncomeTaxClass

from .enums import JurisdictionType
from .us import social_security as us_social_security


class GovernmentPension:
    """The state retirement benefit for one jurisdiction -- the one place that maps a
    `JurisdictionType` to its concrete claiming-age schedule and tax treatment, keeping callers
    jurisdiction-agnostic."""

    def __init__( self, jurisdiction : JurisdictionType ):
        self._jurisdiction = jurisdiction

    def realized_annual_benefit(
            self, entitlement_monthly : Decimal, birthdate : date, claiming_date : date ) -> Decimal:
        """The annual benefit (today's dollars) for claiming on `claiming_date`, given the
        jurisdiction's entitlement -- the monthly benefit at its normal retirement age."""
        if self._jurisdiction is JurisdictionType.US_FEDERAL:
            return us_social_security.realized_annual_benefit(
                entitlement_monthly, birthdate, claiming_date )
        raise NotImplementedError(
            f'No government pension schedule for jurisdiction {self._jurisdiction}.' )

    def spousal_excess_annual_benefit(
            self, entitlement_high_monthly : Decimal, entitlement_low_monthly : Decimal,
            low_birthdate : date, low_claiming_date : date ) -> Decimal:
        """The annual spousal top-up (today's dollars) the lower-entitlement spouse receives on top of
        their own benefit when both are collecting -- a jurisdiction rule (US: up to half the higher
        earner's entitlement, reduced for claiming before the lower spouse's normal retirement age).
        Zero where the jurisdiction has no spousal benefit or the lower entitlement already meets the
        threshold. The caller decides who is higher/lower and gates the both-collecting window."""
        if self._jurisdiction is JurisdictionType.US_FEDERAL:
            return us_social_security.spousal_excess_annual_benefit(
                entitlement_high_monthly, entitlement_low_monthly, low_birthdate, low_claiming_date )
        raise NotImplementedError(
            f'No spousal benefit schedule for jurisdiction {self._jurisdiction}.' )

    def income_tax_class( self ) -> IncomeTaxClass:
        """The income tax-class the benefit is recognized in -- a jurisdiction rule (US Social
        Security carries the partial-inclusion treatment)."""
        if self._jurisdiction is JurisdictionType.US_FEDERAL:
            return IncomeTaxClass.SOCIAL_SECURITY
        raise NotImplementedError(
            f'No government pension tax class for jurisdiction {self._jurisdiction}.' )
