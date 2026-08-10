"""§ Debts: the household's debts as a background-saved facts list.

A debt is a Profile fact -- its kind, name, and current balance (see `Debt`); how it is repaid is a
Plans strategy captured later, not here. This form is the editor over the household's debts the way a
person thinks of them -- one flat list of loans, mortgages included, with no user-visible split
between secured and unsecured. A mortgage secured against a property can also have its balance
adjusted on that property (a convenience surface), but it is the same `Debt` and is fully editable
here too.

**Vehicle (auto) loans are the exception: they are owned by the Vehicles section and the Vehicle plan,
not shown or added here** -- a vehicle stands on its own (its loan's balance in the Vehicles section, its
terms in the Vehicle plan). They are preserved untouched across an edit here (so rebuilding the shown
debts never drops them), and `AUTO` is not an addable kind.

Each row carries its debt's stable `handle` and its `secured_asset` link in hidden fields -- the
handle because Plans reference debts by it (identity must survive edits rather than being reindexed),
and the secured link so editing a mortgage here keeps it tied to its property.
"""
from dataclasses import replace

from django import forms

from common.forms import CHOOSE_PLACEHOLDER, MoneyField

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


class DebtsForm( forms.Form ):
    """Every debt as an auto-saving list: each row is a kind, a name, and the current balance owed;
    a trailing blank row adds another, and an existing row's Remove box drops it. Non-blocking: a row
    materializes only once its kind, name, and balance are all set, so a half-filled row is simply
    ignored. `apply` rebuilds the whole debt list from the rows, each row preserving the debt's stable
    handle and any property it is secured against."""

    # Every debt kind but the vehicle auto loan -- those are managed in the Vehicles section / Vehicle plan.
    _KIND_CHOICES = ( ( '', CHOOSE_PLACEHOLDER ), ) + tuple(
        ( kind.name, kind.label ) for kind in DebtKind if kind is not DebtKind.AUTO )

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._profile = profile
        all_debts = list( profile.debts ) if profile is not None else []
        # Vehicle (auto) loans belong to the Vehicles section / Vehicle plan: not shown here, but kept so
        # rebuilding the shown debts on `apply` never drops them.
        self._vehicle_loans = [ debt for debt in all_debts if debt.kind is DebtKind.AUTO ]
        self._debts         = [ debt for debt in all_debts if debt.kind is not DebtKind.AUTO ]
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
            initial = debt.kind.name if debt else None,
            widget = forms.Select( attrs = { 'class' : 'custom-select' } ) )
        self.fields[ f'name_{index}' ]    = forms.CharField(
            required = False, max_length = 100, initial = debt.name if debt else None,
            widget = forms.TextInput( attrs = { 'class' : 'form-control' } ) )
        self.fields[ f'balance_{index}' ] = MoneyField(
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
        # The shown (non-vehicle) debts are rebuilt from the rows; the vehicle loans are preserved as-is
        # (owned elsewhere). Plans are left untouched: a repayment/paydown/payoff left keyed to a removed
        # debt is reconciled on demand at the run surface, not eagerly here.
        return replace( profile, debts = self._debts_from_rows() + self._vehicle_loans ), plans

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
