"""§ Debts: the household's debts as a background-saved facts list.

A debt is a Profile fact -- its kind, name, and current balance (see `Debt`); how it is repaid is a
Plans strategy captured later, not here. This form is the full editor over *every* debt the way a
person thinks of them -- one flat list of loans, mortgages included, with no user-visible split
between secured and unsecured. A mortgage secured against a property can also have its balance
adjusted on that property (a convenience surface), but it is the same `Debt` and is fully editable
here too.

Each row carries its debt's stable `handle` and its `secured_asset` link in hidden fields -- the
handle because Plans reference debts by it (identity must survive edits rather than being reindexed),
and the secured link so editing a mortgage here keeps it tied to its property.
"""
from dataclasses import replace

from django import forms

from ucfp.inputs.events import CARD_ROLE, LOAN_ROLE
from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt


_HANDLE_PREFIX = 'debt-'


def _minted_debt_handle( taken : set ) -> str:
    """The lowest `debt-N` handle free among `taken` -- a stable identity a new debt keeps across
    edits, since Plans reference debts by handle."""
    index = 1
    while f'{_HANDLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_HANDLE_PREFIX}{index}'


def _reaped_event( event, removed : set ) -> bool:
    """Whether a plan event should be dropped because the debt it targets was removed -- a loan or
    card payoff whose debt is gone."""
    if event.kind is EventKind.LOAN_PAYOFF:
        return event.selections.get( LOAN_ROLE ) in removed
    if event.kind is EventKind.CARD_PAYOFF:
        return event.selections.get( CARD_ROLE ) in removed
    return False


class DebtsForm( forms.Form ):
    """Every debt as an auto-saving list: each row is a kind, a name, and the current balance owed;
    a trailing blank row adds another, and an existing row's Remove box drops it. Non-blocking: a row
    materializes only once its kind, name, and balance are all set, so a half-filled row is simply
    ignored. `apply` rebuilds the whole debt list from the rows, each row preserving the debt's stable
    handle and any property it is secured against."""

    _KIND_CHOICES = ( ( '', 'Type...' ), ) + tuple( ( kind.name, kind.label ) for kind in DebtKind )

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._profile = profile
        self._debts   = list( profile.debts ) if profile is not None else []
        for index in range( len( self._debts ) + 1 ):   # existing rows, then one blank to add
            self._build_row( index )

    def _build_row( self, index : int ):
        debt = self._debts[ index ] if index < len( self._debts ) else None
        self.fields[ f'handle_{index}' ]  = forms.CharField(
            required = False, widget = forms.HiddenInput, initial = debt.handle if debt else None )
        self.fields[ f'secured_{index}' ] = forms.CharField(
            required = False, widget = forms.HiddenInput,
            initial = debt.secured_asset if debt else None )
        self.fields[ f'kind_{index}' ]    = forms.ChoiceField(
            required = False, choices = self._KIND_CHOICES,
            initial = debt.kind.name if debt else None )
        self.fields[ f'name_{index}' ]    = forms.CharField(
            required = False, max_length = 100, initial = debt.name if debt else None )
        self.fields[ f'balance_{index}' ] = forms.DecimalField(
            required = False, min_value = 0, initial = debt.balance if debt else None )
        if debt is not None:
            self.fields[ f'remove_{index}' ] = forms.BooleanField( required = False )

    @property
    def rows( self ) -> list:
        rows = []
        for index in range( len( self._debts ) + 1 ):
            remove = f'remove_{index}'
            rows.append( {
                'handle'  : self[ f'handle_{index}' ],
                'secured' : self[ f'secured_{index}' ],
                'kind'    : self[ f'kind_{index}' ],
                'name'    : self[ f'name_{index}' ],
                'balance' : self[ f'balance_{index}' ],
                'remove'  : self[ remove ] if remove in self.fields else None,
            } )
        return rows

    def apply( self, profile, plans ):
        rebuilt = self._debts_from_rows()
        removed = ( { debt.handle for debt in self._profile.debts }
                    - { debt.handle for debt in rebuilt } )
        plans   = self._reap( plans, removed ) if removed else plans
        return replace( profile, debts = rebuilt ), plans

    @staticmethod
    def _reap( plans, removed : set ):
        """Drop any plan that referenced a debt the user just removed -- a loan's repayment, extra
        principal, and payoff, or a card's paydown plan and payoff -- so a deleted debt leaves
        nothing dangling behind it."""
        return replace(
            plans,
            loan_repayments   = [ r for r in plans.loan_repayments if r.debt_handle not in removed ],
            prepayments       = [ p for p in plans.prepayments if p.loan_handle not in removed ],
            credit_card_plans = [ c for c in plans.credit_card_plans
                                  if c.card_handle not in removed ],
            events            = [ event for event in plans.events if not _reaped_event( event, removed ) ] )

    def _debts_from_rows( self ) -> list:
        # New rows mint a handle free among every debt already in play; existing rows keep the handle
        # (and secured link) their hidden fields carry, so both survive an edit.
        taken = { debt.handle for debt in self._profile.debts }
        debts = []
        for index in range( len( self._debts ) + 1 ):
            if self.cleaned_data.get( f'remove_{index}' ):
                continue
            kind    = self.cleaned_data.get( f'kind_{index}' )
            name    = self.cleaned_data.get( f'name_{index}' )
            balance = self.cleaned_data.get( f'balance_{index}' )
            if not kind or not name or balance is None:
                continue                                     # incomplete row -- not materialized
            handle = self.cleaned_data.get( f'handle_{index}' ) or _minted_debt_handle( taken )
            taken.add( handle )
            debts.append( Debt(
                handle = handle, name = name, kind = DebtKind[ kind ], balance = balance,
                secured_asset = self.cleaned_data.get( f'secured_{index}' ) or None ) )
        return debts
