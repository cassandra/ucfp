"""Retirement benefits: the stated per-person Social Security and pension amounts.

Split out of the Income facts (`income.py`) so the Incomes table is purely the current income the user
enters (salaries, rent, other), and these derived-per-person entitlements -- Social Security's benefit at
full retirement age and a pension's base benefit -- get their own Profile section. Each captures only the
stated benefit *amount*; WHEN each is claimed is a plan, set in the Retirement (Plans) section, not here.
One Social Security and one pension cell per subject, their count fixed by the household.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField

from ucfp.inputs.profile.schemas import GovernmentPensionEntitlement, PensionEntitlement

# The age a pension's base is quoted at. Unused until off-normal-start reduction terms exist; a fixed
# placeholder here, since the start age is a plan (the Retirement section), not a fact.
_PENSION_NORMAL_AGE = 65


class RetirementBenefitsForm( forms.Form ):
    """The per-subject Social Security (benefit at full retirement age) and pension (base benefit) amounts,
    as fixed-count declared MoneyField cells -- one pair per subject. `apply` writes only the entitlement
    facts, leaving the income flows (the Incomes section's job) untouched. Non-blocking: a blank benefit is
    simply not recorded."""

    def __init__( self, data = None, *, profile = None ):
        super().__init__( data )
        self._subjects = list( profile.subjects ) if profile is not None else list()
        self._gov      = { entitlement.subject_handle: entitlement
                           for entitlement in ( profile.government_pension if profile is not None else [] ) }
        self._pension  = { pension.subject_handle: pension
                           for pension in ( profile.pensions if profile is not None else [] ) }
        for m, subject in enumerate( self._subjects ):
            self._add_entitlement_fields( m, subject )

    def _add_entitlement_fields( self, m : int, subject ):
        """The stated Social Security and pension benefits for the subject (FRA / base). When each is
        claimed is a plan, set in the Retirement section; here we capture only the benefit amounts."""
        gov     = self._gov.get( subject.handle )
        pension = self._pension.get( subject.handle )
        self.fields[ self._key( m, 'ssamt' ) ] = MoneyField(
            required = False, min_value = 0,
            initial = gov.monthly_at_normal_age if gov is not None else None )
        self.fields[ self._key( m, 'penamt' ) ] = MoneyField(
            required = False, min_value = 0,
            initial = pension.base_annual_amount if pension is not None else None )

    @staticmethod
    def _key( index : int, part : str ) -> str:
        return f's{index}_{part}'

    @property
    def entitlement_rows( self ) -> list:
        """One row per subject per benefit for the table -- the same Attribution / Income Source / Amount /
        Per shape as the Incomes table, amount-only (the count is set by the people, not edited here)."""
        rows = list()
        for m, subject in enumerate( self._subjects ):
            rows.append( { 'subject_name' : subject.name, 'name' : 'Social Security',
                           'amount' : self[ self._key( m, 'ssamt' ) ], 'cadence' : 'month',
                           'note' : 'benefit at full retirement age' } )
            rows.append( { 'subject_name' : subject.name, 'name' : 'Pension',
                           'amount' : self[ self._key( m, 'penamt' ) ], 'cadence' : 'year',
                           'note' : 'base benefit' } )
        return rows

    def apply( self, profile, plans ):
        return replace(
            profile, government_pension = self._entitlements(), pensions = self._pensions() ), plans

    def _entitlements( self ) -> list:
        entitlements = list()
        for m, subject in enumerate( self._subjects ):
            amount = self.cleaned_data.get( self._key( m, 'ssamt' ) )
            if amount is not None:
                entitlements.append( GovernmentPensionEntitlement(
                    subject_handle = subject.handle, monthly_at_normal_age = amount ) )
        return entitlements

    def _pensions( self ) -> list:
        pensions = list()
        for m, subject in enumerate( self._subjects ):
            amount = self.cleaned_data.get( self._key( m, 'penamt' ) )
            if amount is not None:
                pensions.append( PensionEntitlement(
                    subject_handle = subject.handle, base_annual_amount = amount,
                    normal_start_age = _PENSION_NORMAL_AGE ) )
        return pensions
