"""§5 income: the editable income *facts* table.

Income is a list of flows -- the income twin of the expense side (see `IncomeFlow`). This module
presents the FACTS as one editable table: a row per general income line (salary, consulting, ...), a
row per rental property's rent, and two entitlement rows per subject (Social Security, pension). Each
row captures the amount (a general line also its name and who receives it) and, for the entitlements,
the stated benefit. WHEN each income runs -- the start/stop windows and the benefit claiming ages -- is
a *plan*, edited in the separate Retirement section (`retirement.py`), not here; this form leaves the
Plans untouched.

Each general flow carries a stable `handle` (hidden, minted on first save) so the Retirement section's
per-flow timing keys onto it across edits. The table auto-saves; validation is deliberately
non-blocking -- an incomplete row simply does not materialize (no flow / no entitlement written).
"""
from dataclasses import replace

from django import forms

from common.forms import CHOOSE_PLACEHOLDER, MoneyField
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.inputs.profile.schemas import GovernmentPensionEntitlement, IncomeFlow, PensionEntitlement

_RENTAL_INTERVAL = Duration( 1, TimeUnit.MONTH )   # rent is a monthly item; general income a stream
_INCOME_HANDLE_PREFIX = 'income-'                  # a general flow's stable handle; Retirement keys on it
# The age a pension's base is quoted at. Unused until off-normal-start reduction terms exist; a fixed
# placeholder here, since the start age is a plan (the Retirement section), not a fact.
_PENSION_NORMAL_AGE = 65


class IncomeTableForm( forms.Form ):
    """The income *facts* table: each general line's name / recipient / amount (with a blank row to add
    one), each rental's rent, and the SS and pension benefit amounts per subject. `apply` rebuilds the
    profile's income flows (rental preserved by `property_handle`, general from the rows, each with a
    stable `handle`) and the entitlement facts. Editing timing is the Retirement section's job; the only
    Plans it touches is to reap a deleted flow's orphaned timing."""

    _EXTRA_ROWS = 1
    # A general row's subject may be a person (their wages, taxed per worker) or the whole household
    # (other ordinary income, aggregate-taxed). This sentinel is the dropdown value for the latter.
    _HOUSEHOLD = '__household__'

    def __init__( self, data = None, *, profile = None ):
        super().__init__( data )
        self._profile  = profile
        self._subjects = list( profile.subjects ) if profile is not None else list()
        flows          = list( profile.income_flows ) if profile is not None else list()
        self._general  = [ flow for flow in flows if flow.property_handle is None ]
        self._rentals  = ( [ asset for asset in profile.assets
                             if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL ]
                           if profile is not None else list() )
        rental_flows   = { flow.property_handle: flow for flow in flows
                           if flow.property_handle is not None }
        self._gov      = { entitlement.subject_handle: entitlement
                           for entitlement in ( profile.government_pension if profile is not None else [] ) }
        self._pension  = { pension.subject_handle: pension
                           for pension in ( profile.pensions if profile is not None else [] ) }
        self._general_rows = len( self._general ) + self._EXTRA_ROWS
        for i in range( self._general_rows ):
            self._add_general_fields( i, self._general[ i ] if i < len( self._general ) else None )
        for k, rental in enumerate( self._rentals ):
            self._add_rental_fields( k, rental_flows.get( rental.handle ) )
        for m, subject in enumerate( self._subjects ):
            self._add_entitlement_fields( m, subject )

    # --- field construction ------------------------------------------------

    def _add_general_fields( self, i : int, flow ):
        self.fields[ self._key( 'g', i, 'name' ) ] = forms.CharField(
            required = False, max_length = 100, initial = flow.name if flow is not None else None,
            widget = forms.TextInput( attrs = { 'class' : 'form-control' } ) )
        subject = forms.ChoiceField(
            required = False, choices = self._subject_choices(),
            widget = forms.Select( attrs = { 'class' : 'custom-select' } ) )
        if flow is not None:
            subject.initial = flow.subject_handle if flow.subject_handle is not None else self._HOUSEHOLD
            self.fields[ self._key( 'g', i, 'remove' ) ] = forms.BooleanField( required = False )
            self.fields[ self._key( 'g', i, 'handle' ) ] = forms.CharField(
                required = False, widget = forms.HiddenInput, initial = flow.handle )
        self.fields[ self._key( 'g', i, 'subject' ) ] = subject
        self.fields[ self._key( 'g', i, 'amount' ) ]  = MoneyField(
            required = False, min_value = 0, initial = flow.amount if flow is not None else None )

    def _add_rental_fields( self, k : int, flow ):
        self.fields[ self._key( 'r', k, 'amount' ) ] = MoneyField(
            required = False, min_value = 0, initial = flow.amount if flow is not None else None )

    def _add_entitlement_fields( self, m : int, subject ):
        """The stated Social Security and pension benefits for the subject (FRA / base). When each is
        claimed is a plan, set in the Retirement section; here we capture only the benefit amounts."""
        gov     = self._gov.get( subject.handle )
        pension = self._pension.get( subject.handle )
        self.fields[ self._key( 's', m, 'ssamt' ) ] = MoneyField(
            required = False, min_value = 0,
            initial = gov.monthly_at_normal_age if gov is not None else None )
        self.fields[ self._key( 's', m, 'penamt' ) ] = MoneyField(
            required = False, min_value = 0,
            initial = pension.base_annual_amount if pension is not None else None )

    @staticmethod
    def _key( prefix : str, index : int, part : str ) -> str:
        return f'{prefix}{index}_{part}'

    def _subject_choices( self ) -> list:
        candidates = [ ( subject.handle, subject.name ) for subject in self._subjects ]
        household  = [ ( self._HOUSEHOLD, 'Household' ) ]
        if len( candidates ) == 1:
            return candidates + household
        return [ ( '', CHOOSE_PLACEHOLDER ) ] + candidates + household

    def _default_subject( self, subject : str ) -> str:
        """The chosen subject, or the sole subject when there is only one; None when several and none
        was chosen."""
        if subject:
            return subject
        return self._subjects[ 0 ].handle if len( self._subjects ) == 1 else None

    # --- template rows -----------------------------------------------------

    @property
    def income_rows( self ) -> list:
        rows = list()
        for i in range( self._general_rows ):
            existing = i < len( self._general )
            rows.append( {
                'kind'    : 'general',
                'name'    : self[ self._key( 'g', i, 'name' ) ],
                'subject' : self[ self._key( 'g', i, 'subject' ) ],
                'amount'  : self[ self._key( 'g', i, 'amount' ) ],
                'handle'  : self[ self._key( 'g', i, 'handle' ) ] if existing else None,
                'cadence' : 'year',
                'remove'  : self[ self._key( 'g', i, 'remove' ) ] if existing else None } )
        for m, subject in enumerate( self._subjects ):
            rows.append( { 'kind' : 'entitlement', 'subject_name' : subject.name, 'name' : 'Social Security',
                           'amount' : self[ self._key( 's', m, 'ssamt' ) ], 'cadence' : 'month',
                           'note' : 'benefit at full retirement age' } )
            rows.append( { 'kind' : 'entitlement', 'subject_name' : subject.name, 'name' : 'Pension',
                           'amount' : self[ self._key( 's', m, 'penamt' ) ], 'cadence' : 'year',
                           'note' : 'base benefit' } )
        # Rentals last -- after the general lines and each person's entitlements -- since they are a
        # household-level, per-property source rather than an individual's income.
        for k, rental in enumerate( self._rentals ):
            rows.append( {
                'kind'         : 'rental', 'name' : rental.name, 'subject_name' : 'Rental',
                'amount'       : self[ self._key( 'r', k, 'amount' ) ], 'cadence' : 'month' } )
        return rows

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        rebuilt = self._general_flows() + self._rental_flows()
        removed = ( { flow.handle for flow in self._profile.income_flows }
                    - { flow.handle for flow in rebuilt } )
        # Editing timing is the Retirement section's job, but a deleted flow's orphaned timing is reaped
        # here (the only place a flow is removed) -- else it could re-bind to a later flow reclaiming its
        # `income-N` handle. Mirrors how the Debts section reaps a removed debt's repayment plan.
        plans   = _plans_without_income_timing( plans, removed ) if removed else plans
        updated_profile = replace(
            profile, income_flows = rebuilt,
            government_pension = self._entitlements(), pensions = self._pensions() )
        return updated_profile, plans

    def _general_flows( self ) -> list:
        flows, taken = list(), { flow.handle for flow in self._general }
        for i in range( self._general_rows ):
            if i < len( self._general ) and self.cleaned_data.get( self._key( 'g', i, 'remove' ) ):
                continue
            amount  = self.cleaned_data.get( self._key( 'g', i, 'amount' ) )
            subject = self._default_subject( self.cleaned_data.get( self._key( 'g', i, 'subject' ) ) )
            if amount is None or not subject:
                continue
            household = subject == self._HOUSEHOLD
            submitted = self.cleaned_data.get( self._key( 'g', i, 'handle' ) )
            handle    = submitted or _minted_income_handle( taken )   # existing row keeps its handle
            taken.add( handle )
            flows.append( IncomeFlow(
                handle = handle,
                name = self.cleaned_data.get( self._key( 'g', i, 'name' ) ) or 'Income',
                subject_handle = None if household else subject,
                income_tax_class = IncomeTaxClass.ORDINARY if household else IncomeTaxClass.WAGES,
                amount = amount ) )
        return flows

    def _rental_flows( self ) -> list:
        flows = list()
        for k, rental in enumerate( self._rentals ):
            amount = self.cleaned_data.get( self._key( 'r', k, 'amount' ) )
            if amount is None:
                continue
            flows.append( IncomeFlow(
                handle = rental.handle, name = rental.name, subject_handle = None,   # rent is household
                income_tax_class = IncomeTaxClass.GROSS_RENTAL, amount = amount,
                interval = _RENTAL_INTERVAL, property_handle = rental.handle ) )
        return flows

    def _entitlements( self ) -> list:
        entitlements = list()
        for m, subject in enumerate( self._subjects ):
            amount = self.cleaned_data.get( self._key( 's', m, 'ssamt' ) )
            if amount is not None:
                entitlements.append( GovernmentPensionEntitlement(
                    subject_handle = subject.handle, monthly_at_normal_age = amount ) )
        return entitlements

    def _pensions( self ) -> list:
        pensions = list()
        for m, subject in enumerate( self._subjects ):
            amount = self.cleaned_data.get( self._key( 's', m, 'penamt' ) )
            if amount is not None:
                pensions.append( PensionEntitlement(
                    subject_handle = subject.handle, base_annual_amount = amount,
                    normal_start_age = _PENSION_NORMAL_AGE ) )
        return pensions


def _plans_without_income_timing( plans, removed_handles : set ):
    """`plans` with the per-flow `IncomeTiming` for the removed income flows dropped -- the orphan reap a
    flow deletion triggers, so a stale window cannot re-bind to a later flow that reclaims its handle."""
    return replace( plans, income_timing = [ entry for entry in plans.income_timing
                                             if entry.flow_handle not in removed_handles ] )


def _minted_income_handle( taken : set ) -> str:
    """The lowest `income-N` handle free among `taken` -- a general flow's stable identity, so the
    Retirement section's per-flow timing keys onto it across edits."""
    index = 1
    while f'{_INCOME_HANDLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_INCOME_HANDLE_PREFIX}{index}'
