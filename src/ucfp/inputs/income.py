"""Incomes: the editable income *facts* table.

Income is a list of flows -- the income twin of the expense side (see `IncomeFlow`). This module presents
the FACTS as one editable table: the general income lines (salary, consulting, ...) as a rowset the user
adds to and removes from, plus a row per rental property's rent. Each row captures the amount (a general
line also its name and who receives it). WHEN each income runs -- the start/stop windows -- is a *plan*,
edited in the separate Retirement section (`retirement.py`), not here; this form leaves the Plans
untouched. The per-person Social Security and pension benefits are a sibling Profile section
(`retirement_benefits.py`), so this table is purely the current income the user enters.

The general lines are a rowset: repeated same-name inputs (`income_*`) read as parallel lists (getlist),
added and removed client-side (`js-rowset`, inputs.js) rather than through a phantom trailing row. Each
general line carries a stable `handle` (hidden, minted on first save) so the Retirement section's per-flow
timing keys onto it across edits. The fixed rental rows stay declared MoneyField cells, their count set by
the properties. The table auto-saves; validation is deliberately non-blocking -- an incomplete row simply
does not materialize -- save that a negative amount is a genuine error and re-renders.
"""
from dataclasses import replace
from itertools import zip_longest

from django import forms

from common.forms import CHOOSE_PLACEHOLDER, MoneyField
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.inputs.profile.schemas import IncomeFlow

_RENTAL_INTERVAL = Duration( 1, TimeUnit.MONTH )   # rent is a monthly item; general income a stream
_INCOME_HANDLE_PREFIX = 'income-'                  # a general flow's stable handle; Retirement keys on it


class IncomeTableForm( forms.Form ):
    """The income *facts* table. The general lines are a rowset -- `income_name` / `income_subject` /
    `income_amount` / `income_handle` posted as parallel lists, one entry per row, added and removed
    client-side. The rental rents are fixed-count declared MoneyField cells. `apply` rebuilds the profile's
    income flows (rental preserved by `property_handle`, general from the rowset, each with a stable
    `handle`), leaving the entitlement facts to the Retirement benefits section. Editing timing is the
    Retirement section's job; the only Plans it touches is to reap a deleted flow's orphaned timing."""

    # A general row's subject may be a person (their wages, taxed per worker) or the whole household (other
    # ordinary income, aggregate-taxed). This sentinel is the dropdown value for the latter.
    _HOUSEHOLD = '__household__'
    # The repeated field names of a general rowset row -- one source with the template's inputs (see
    # `names`), read as parallel getlists and zipped by position.
    _G_NAME    = 'income_name'
    _G_SUBJECT = 'income_subject'
    _G_AMOUNT  = 'income_amount'
    _G_HANDLE  = 'income_handle'

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
        # One MoneyField reused to parse each posted rowset amount, so the general cells strip separators
        # and reject negatives exactly as the declared cells do.
        self._amount_field   = MoneyField( required = False, min_value = 0 )
        self._general_errors = dict()                  # rowset index -> amount error message (set in clean)
        for k, rental in enumerate( self._rentals ):
            self._add_rental_field( k, rental_flows.get( rental.handle ) )

    # --- field construction (fixed rows only) ------------------------------

    def _add_rental_field( self, k : int, flow ):
        self.fields[ self._key( 'r', k, 'amount' ) ] = MoneyField(
            required = False, min_value = 0, initial = flow.amount if flow is not None else None )

    @staticmethod
    def _key( prefix : str, index : int, part : str ) -> str:
        return f'{prefix}{index}_{part}'

    # --- general rowset ----------------------------------------------------

    @property
    def names( self ) -> dict:
        """The general rowset's field names -- one source shared with the template's inputs and the getlist
        keys below, so the two cannot drift."""
        return { 'name' : self._G_NAME, 'subject' : self._G_SUBJECT,
                 'amount' : self._G_AMOUNT, 'handle' : self._G_HANDLE }

    def _posted_general( self ):
        """The posted general rows as `(name, subject, amount, handle)` tuples, zipped by position -- one
        per rendered rowset row (the blank <template> prototype is inert, so it never posts)."""
        return zip_longest(
            self.data.getlist( self._G_NAME ), self.data.getlist( self._G_SUBJECT ),
            self.data.getlist( self._G_AMOUNT ), self.data.getlist( self._G_HANDLE ), fillvalue = '' )

    @property
    def general_rows( self ) -> list:
        """The general lines for the rowset. Bound (a re-render after an edit): the submitted values, so
        typing survives an error re-render, each with any amount error. Unbound (first load): the stored
        flows."""
        if self.is_bound:
            return [ { 'name' : name, 'subject' : subject, 'amount' : amount, 'handle' : handle,
                       'error' : self._general_errors.get( i ) }
                     for i, ( name, subject, amount, handle ) in enumerate( self._posted_general() ) ]
        return [ { 'name' : flow.name,
                   'subject' : flow.subject_handle if flow.subject_handle is not None else self._HOUSEHOLD,
                   'amount' : flow.amount, 'handle' : flow.handle, 'error' : None }
                 for flow in self._general ]

    @property
    def subject_choices( self ) -> list:
        candidates = [ ( subject.handle, subject.name ) for subject in self._subjects ]
        household  = [ ( self._HOUSEHOLD, 'Household' ) ]
        if len( candidates ) == 1:
            return candidates + household
        return [ ( '', CHOOSE_PLACEHOLDER ) ] + candidates + household

    def _default_subject( self, subject : str ) -> str:
        """The chosen subject, or the sole subject when there is only one; None when several and none was
        chosen."""
        if subject:
            return subject
        return self._subjects[ 0 ].handle if len( self._subjects ) == 1 else None

    def _parse_amount( self, raw : str ):
        """A posted amount as a non-negative Decimal, or None when blank or invalid -- the declared cells'
        own parse, reused."""
        try:
            return self._amount_field.clean( raw )
        except forms.ValidationError:
            return None

    # --- template rows (fixed) ---------------------------------------------

    @property
    def rental_rows( self ) -> list:
        return [ { 'name' : rental.name, 'amount' : self[ self._key( 'r', k, 'amount' ) ], 'cadence' : 'month' }
                 for k, rental in enumerate( self._rentals ) ]

    # --- validation --------------------------------------------------------

    def clean( self ):
        """Surface a negative general amount as a genuine error (so the pane re-renders it), keyed to its
        row for the template; a blank or otherwise-incomplete row stays non-blocking."""
        cleaned = super().clean()
        for i, ( _name, _subject, amount, _handle ) in enumerate( self._posted_general() ):
            if not amount:
                continue
            try:
                self._amount_field.clean( amount )
            except forms.ValidationError as error:
                self._general_errors[ i ] = ' '.join( error.messages )
        if self._general_errors:
            raise forms.ValidationError( 'Check the highlighted income amounts.' )
        return cleaned

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        rebuilt = self._general_flows() + self._rental_flows()
        removed = ( { flow.handle for flow in self._profile.income_flows }
                    - { flow.handle for flow in rebuilt } )
        # Editing timing is the Retirement section's job, but a deleted flow's orphaned timing is reaped
        # here (the only place a flow is removed) -- else it could re-bind to a later flow reclaiming its
        # `income-N` handle. Mirrors how the Debts section reaps a removed debt's repayment plan.
        plans   = _plans_without_income_timing( plans, removed ) if removed else plans
        return replace( profile, income_flows = rebuilt ), plans

    def _general_flows( self ) -> list:
        taken = { handle for handle in self.data.getlist( self._G_HANDLE ) if handle }
        flows = list()
        for name, subject_raw, amount_raw, handle_raw in self._posted_general():
            amount  = self._parse_amount( amount_raw )
            subject = self._default_subject( subject_raw )
            if amount is None or not subject:
                continue
            household = subject == self._HOUSEHOLD
            handle    = handle_raw or _minted_income_handle( taken )   # existing row keeps its handle
            taken.add( handle )
            flows.append( IncomeFlow(
                handle = handle, name = name or 'Income',
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
