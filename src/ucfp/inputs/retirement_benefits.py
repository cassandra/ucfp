"""Retirement benefits: the stated per-person Social Security and pension amounts.

Split out of the Income facts (`income.py`) so the Incomes table is purely the current income the user
enters (salaries, rent, other), and these derived-per-person entitlements -- Social Security's benefit at
full retirement age and a pension's base benefit -- get their own Profile section. Each captures only the
stated benefit *amount*; WHEN each is claimed is a plan, set in the Retirement (Plans) section, not here.
One Social Security and one pension cell per subject, their count fixed by the household.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import MoneyField

from ucfp.environment.constants import AppConst
from ucfp.accounts.enums import IncomeTaxClass
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.inputs.profile.schemas import GovernmentPensionEntitlement, PensionEntitlement

# The age a pension's base is quoted at. Unused until off-normal-start reduction terms exist; a fixed
# placeholder here, since the start age is a plan (the Retirement section), not a fact.
_PENSION_NORMAL_AGE = 65


def subject_wage_total( profile, subject_handle : str ) -> Decimal:
    """The subject's total annual covered wages -- the sum of their WAGES income flows. Household income
    (rent, other) is not attributed to a person, so it is excluded; only a person's own wages count toward
    a Social Security benefit. The seed for the FRA-benefit estimate."""
    return sum(
        ( flow.amount for flow in profile.income_flows
          if flow.subject_handle == subject_handle and flow.income_tax_class == IncomeTaxClass.WAGES ),
        Decimal( 0 ) )


class SocialSecurityEstimatorForm( forms.Form ):
    """The FRA-benefit calculator's two fields: the average annual income (seeded from the subject's summed
    wages) and the resulting estimated monthly benefit at full retirement age. The income drives the
    estimate -- editing it recomputes the benefit -- and the benefit stays editable so the user can enter a
    figure they already know. Rendering and parsing only; the estimate itself comes from the jurisdiction
    facade (`GovernmentPension`)."""

    income      = MoneyField( required = False, min_value = 0 )
    fra_benefit = MoneyField( required = False, min_value = 0 )

    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )
        # Mark the income input for the calculator's debounced recompute (inputs.js): as the user types, it
        # posts the recompute form, which swaps the benefit field while the modal stays open.
        income = self.fields[ 'income' ].widget
        income.attrs[ 'class' ] = f'{income.attrs.get( "class", "" )} {AppConst.SS_ESTIMATE_INCOME_CLASS}'.strip()


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
        # Whether to offer the benefit calculator beside the Social Security cell -- a jurisdiction
        # capability asked of the facade, never a jurisdiction test here (the input layer stays neutral).
        self._can_estimate = profile is not None and \
            GovernmentPension( profile.jurisdiction_type ).has_benefit_estimator()
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
                           'note' : 'benefit at full retirement age',
                           # The subject the calculator estimates for -- present only where the
                           # jurisdiction has an estimator, so the table shows the opener just there.
                           'estimate_handle' : subject.handle if self._can_estimate else None } )
            rows.append( { 'subject_name' : subject.name, 'name' : 'Pension',
                           'amount' : self[ self._key( m, 'penamt' ) ], 'cadence' : 'year',
                           'note' : 'base benefit', 'estimate_handle' : None } )
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


def applied_government_benefit( profile, subject_handle : str, monthly ):
    """`profile` with one subject's Social Security entitlement set to `monthly` (a blank/None clears it),
    every other subject's entitlement left untouched -- the targeted write the calculator's Confirm makes.
    Distinct from `RetirementBenefitsForm.apply`, which rewrites the whole table from a full submission."""
    kept = [ entitlement for entitlement in profile.government_pension
             if entitlement.subject_handle != subject_handle ]
    if monthly is not None:
        kept.append( GovernmentPensionEntitlement(
            subject_handle = subject_handle, monthly_at_normal_age = monthly ) )
    return replace( profile, government_pension = kept )
