"""Shared mortgage fields for the property forms.

The residence (`HomeForm`) and each rental (`RentalForm`) carry the same optional mortgage: the same
six fields, the same "is there one?" inference, the same core-term validation, and the same mapping
to a `LoanProfile` and an extra-principal `LoanPrepayment`. This mixin owns all of that. Each form
supplies only what genuinely differs -- the loan's handle, name, interest tax class, and property,
and (for the residence) that a mortgage is possible only when owning.

Combined with a concrete form as a base class; Django's form metaclass collects the fields declared
here onto the final form. The mortgage renders as an optional block (the js-optional pattern in
inputs.js): its presence is inferred from the fields being filled, so there is no separate "there is
a mortgage" checkbox.
"""
from django import forms

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.schemas import LoanPrepayment
from ucfp.inputs.profile.schemas import LoanProfile
from ucfp.inputs.widgets import IsoDateInput


class MortgageFields( forms.Form ):

    mortgage_origination = forms.DateField(
        label = 'Loan start date', required = False,
        widget = IsoDateInput( context = AppConst.DATE_CONTEXT_PAST ) )
    mortgage_original_amount = forms.DecimalField(
        label = 'Original loan amount', required = False, min_value = 0 )
    mortgage_rate = forms.DecimalField(
        label = 'Interest rate (%)', required = False, min_value = 0 )
    mortgage_term_years = forms.IntegerField(
        label = 'Loan term (years)', required = False, min_value = 1 )
    mortgage_current_balance = forms.DecimalField(
        label = 'Balance owed now (optional)', required = False, min_value = 0 )
    mortgage_extra_principal = forms.DecimalField(
        label = 'Extra principal per month (optional)', required = False, min_value = 0 )

    MORTGAGE_FIELD_NAMES = (
        'mortgage_origination', 'mortgage_original_amount', 'mortgage_rate',
        'mortgage_term_years', 'mortgage_current_balance', 'mortgage_extra_principal' )

    _CORE_TERMS = (
        ( 'mortgage_origination'    , 'Enter the loan start date.' ),
        ( 'mortgage_original_amount', 'Enter the original loan amount.' ),
        ( 'mortgage_rate'           , 'Enter the interest rate.' ),
        ( 'mortgage_term_years'     , 'Enter the loan term.' ) )

    @property
    def mortgage_fields( self ):
        """The mortgage bound fields, rendered together inside the optional block."""
        return [ self[ name ] for name in self.MORTGAGE_FIELD_NAMES ]

    def _has_mortgage( self ) -> bool:
        """A mortgage is inferred from any of its fields being filled -- no opt-in checkbox. Forms
        that allow a mortgage only in some states (e.g. an owned residence) narrow this."""
        return any( self.cleaned_data.get( name ) is not None for name in self.MORTGAGE_FIELD_NAMES )

    def _validate_mortgage( self ):
        """When a mortgage is present, require its core terms, so a half-entered one is rejected
        rather than silently dropped. Used by forms that save on an explicit submit; a background-
        saving form omits this and relies on `_mortgage_complete` to materialize only a whole loan."""
        if not self._has_mortgage():
            return
        for field, message in self._CORE_TERMS:
            if self.cleaned_data.get( field ) is None:
                self.add_error( field, message )

    def _mortgage_complete( self ) -> bool:
        """Whether all core loan terms are present -- the condition for materializing a mortgage. A
        half-entered mortgage does not materialize (keeping it out of `LoanProfile` with None
        fields); a validating form additionally flags it via `_validate_mortgage`."""
        return all( self.cleaned_data.get( field ) is not None for field, _ in self._CORE_TERMS )

    @staticmethod
    def _mortgage_initial( mortgage, prepayment ) -> dict:
        """Initial values for the mortgage fields from a saved loan and its optional extra-principal
        prepayment; empty when there is no loan."""
        if mortgage is None:
            return dict()
        initial = {
            'mortgage_origination'     : mortgage.origination_date,
            'mortgage_original_amount' : mortgage.original_amount,
            'mortgage_rate'            : mortgage.interest_rate.fraction * 100,
            'mortgage_term_years'      : mortgage.original_term.months() // 12,
            'mortgage_current_balance' : mortgage.current_balance,
        }
        if prepayment is not None:
            initial[ 'mortgage_extra_principal' ] = prepayment.annual_amount / 12
        return initial

    def _mortgage_loan( self, *, handle, name, interest_class, property_handle ):
        """The `LoanProfile` for a complete mortgage, or None when there is none or it is only
        partly entered."""
        if not self._mortgage_complete():
            return None
        cleaned = self.cleaned_data
        return LoanProfile(
            handle = handle, name = name,
            origination_date = cleaned[ 'mortgage_origination' ],
            original_amount = cleaned[ 'mortgage_original_amount' ],
            interest_rate = Rate.percent( cleaned[ 'mortgage_rate' ] ),
            original_term = Duration( cleaned[ 'mortgage_term_years' ], TimeUnit.YEAR ),
            current_balance = cleaned.get( 'mortgage_current_balance' ),
            interest_class = interest_class, property_handle = property_handle )

    def _mortgage_prepayment( self, loan_handle ):
        """The extra-principal `LoanPrepayment` when a mortgage is present and an extra amount was
        given, else None."""
        extra = self.cleaned_data.get( 'mortgage_extra_principal' )
        if not self._mortgage_complete() or not extra:
            return None
        return LoanPrepayment( loan_handle = loan_handle, annual_amount = extra * 12 )
