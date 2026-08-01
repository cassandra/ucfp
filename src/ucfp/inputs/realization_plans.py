"""The Tax Planning realization tables -- Roth conversions and scheduled withdrawals.

Both are the same shape: a table of planned realizations of a retirement account, each one-time (a single
age) or a recurring ladder (every N years over an age window). A conversion moves pre-tax money to the
owner's Roth; a withdrawal draws a retirement account to cash. `RealizationPlanForm` holds the shared
table -- source account, amount, an optional "every N years" cadence (blank = one-time), and the age
window -- and each subclass supplies only its source account classes, handle/field prefixes, and the
Plans list + entry type it reads and writes. The tables auto-save; validation is non-blocking (an
incomplete row simply does not materialize). Both write only the Plans.
"""
from dataclasses import replace

from django import forms

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.cadence import add_optional_cadence_fields, cadence_cells, read_optional_cadence
from ucfp.inputs.plans.schemas import RothConversion, Withdrawal
from ucfp.parameter_sets.enums import CadenceDomain

_PRETAX              = AssetClass.PRETAX_RETIREMENT
_RETIREMENT_CLASSES  = ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH )
_REALIZATION_DOMAIN  = CadenceDomain.WK_MO_YR   # weekly / monthly / yearly; blank magnitude = one-time


class RealizationPlanForm( forms.Form ):
    """Shared base for a Tax Planning realization table: a row per plan -- a source account, amount, an
    optional cadence (an "every N weeks/months/years" control whose blank magnitude means one-time), and
    the age window (the "From age" alone for a one-time plan, both "From age" and "Until age" for a ladder)
    -- plus a blank row to add one, keyed to a stable handle. `apply` rebuilds the subclass's Plans list
    from the rows. A subclass sets `_ACCOUNT_CLASSES`, `_HANDLE_PREFIX`, `_KEY_PREFIX`, and implements the
    three Plans hooks."""

    _EXTRA_ROWS      = 1
    _ACCOUNT_CLASSES = ()      # subclass: the valid source asset classes
    _HANDLE_PREFIX   = ''      # subclass: minted handle prefix (e.g. 'conversion-')
    _KEY_PREFIX      = ''      # subclass: field-name namespace (e.g. 'v')

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._accounts = ( [ asset for asset in profile.assets
                             if asset.asset_class in self._ACCOUNT_CLASSES ]
                           if profile is not None else list() )
        self._entries  = list( self._plan_entries( plans ) ) if plans is not None else list()
        self._rows     = len( self._entries ) + self._EXTRA_ROWS
        for i in range( self._rows ):
            self._add_row_fields( i, self._entries[ i ] if i < len( self._entries ) else None )

    # --- subclass hooks ----------------------------------------------------

    def _plan_entries( self, plans ) -> list:
        """The subclass's current Plans list (e.g. `plans.roth_conversions`)."""
        raise NotImplementedError

    def _build_entry( self, handle, source, amount, interval, start_age, end_age ):
        """The subclass's Plans entry (a `RothConversion` or a `Withdrawal`) from a row's values."""
        raise NotImplementedError

    def _updated_plans( self, plans, entries ):
        """`plans` with the rebuilt entries stored on the subclass's field."""
        raise NotImplementedError

    @property
    def has_accounts( self ) -> bool:
        """Whether the household has an account of the right kind to plan against -- else the pane says
        so rather than offering an empty picker."""
        return bool( self._accounts )

    # --- field construction ------------------------------------------------

    def _add_row_fields( self, i : int, entry ):
        self.fields[ self._key( i, 'source' ) ] = forms.ChoiceField(
            required = False, choices = self._account_choices(),
            initial = entry.source_handle if entry is not None else None )
        self.fields[ self._key( i, 'amount' ) ] = forms.DecimalField(
            required = False, min_value = 0, initial = entry.amount if entry is not None else None )
        add_optional_cadence_fields(
            self, self._cadence( i ), entry.interval if entry is not None else None,
            _REALIZATION_DOMAIN )
        self.fields[ self._key( i, 'start_age' ) ] = forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = entry.start_age if entry is not None else None )
        self.fields[ self._key( i, 'end_age' ) ] = forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = entry.end_age if entry is not None else None )
        if entry is not None:
            self.fields[ self._key( i, 'handle' ) ] = forms.CharField(
                required = False, widget = forms.HiddenInput, initial = entry.handle )
            self.fields[ self._key( i, 'remove' ) ] = forms.BooleanField( required = False )

    def _account_choices( self ) -> list:
        candidates = [ ( asset.handle, asset.name ) for asset in self._accounts ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    def _key( self, index : int, part : str ) -> str:
        return f'{self._KEY_PREFIX}{index}_{part}'

    def _cadence( self, index : int ) -> str:
        return f'{self._KEY_PREFIX}{index}_cad'

    def _sole_account( self ):
        """The lone account when there is only one (its picker has no placeholder, so a blank submit
        still means it); None when several and none was chosen."""
        return self._accounts[ 0 ].handle if len( self._accounts ) == 1 else None

    # --- template rows -----------------------------------------------------

    @property
    def plan_rows( self ) -> list:
        rows = list()
        for i in range( self._rows ):
            existing = i < len( self._entries )
            interval = self._entries[ i ].interval if existing else None
            rows.append( {
                'source'    : self[ self._key( i, 'source' ) ],
                'amount'    : self[ self._key( i, 'amount' ) ],
                'cadence'   : cadence_cells( self, self._cadence( i ), interval, _REALIZATION_DOMAIN ),
                'start_age' : self[ self._key( i, 'start_age' ) ],
                'end_age'   : self[ self._key( i, 'end_age' ) ],
                'handle'    : self[ self._key( i, 'handle' ) ] if existing else None,
                'remove'    : self[ self._key( i, 'remove' ) ] if existing else None } )
        return rows

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        return profile, self._updated_plans( plans, self._rebuilt() )

    def _rebuilt( self ) -> list:
        entries, taken = list(), { entry.handle for entry in self._entries }
        for i in range( self._rows ):
            existing = i < len( self._entries )
            if existing and self.cleaned_data.get( self._key( i, 'remove' ) ):
                continue
            source = self.cleaned_data.get( self._key( i, 'source' ) ) or self._sole_account()
            amount = self.cleaned_data.get( self._key( i, 'amount' ) )
            if not source or amount is None:
                continue                                       # incomplete row -- not materialized
            submitted = self.cleaned_data.get( self._key( i, 'handle' ) )
            handle    = submitted or self._minted_handle( taken )
            taken.add( handle )
            interval = read_optional_cadence( self, self._cadence( i ), _REALIZATION_DOMAIN )
            entries.append( self._build_entry(
                handle, source, amount, interval,
                self.cleaned_data.get( self._key( i, 'start_age' ) ),
                self.cleaned_data.get( self._key( i, 'end_age' ) ) ) )
        return entries

    def _minted_handle( self, taken : set ) -> str:
        """The lowest `{prefix}N` handle free among `taken` -- a row's stable identity, so edits
        round-trip its cadence/window rather than rebuilding it fresh each save."""
        index = 1
        while f'{self._HANDLE_PREFIX}{index}' in taken:
            index += 1
        return f'{self._HANDLE_PREFIX}{index}'


class ConversionsForm( RealizationPlanForm ):
    """Roth conversions: move pre-tax retirement money to the owner's Roth (resolved at materialize)."""

    _ACCOUNT_CLASSES = ( _PRETAX, )
    _HANDLE_PREFIX   = 'conversion-'
    _KEY_PREFIX      = 'v'

    def _plan_entries( self, plans ) -> list:
        return plans.roth_conversions

    def _build_entry( self, handle, source, amount, interval, start_age, end_age ):
        return RothConversion(
            handle = handle, source_handle = source, amount = amount, interval = interval,
            start_age = start_age, end_age = end_age )

    def _updated_plans( self, plans, entries ):
        return replace( plans, roth_conversions = entries )


class WithdrawalsForm( RealizationPlanForm ):
    """Scheduled withdrawals: deliberate draws from a retirement account (pre-tax or Roth) to cash."""

    _ACCOUNT_CLASSES = _RETIREMENT_CLASSES
    _HANDLE_PREFIX   = 'withdrawal-'
    _KEY_PREFIX      = 'w'

    def _plan_entries( self, plans ) -> list:
        return plans.withdrawals

    def _build_entry( self, handle, source, amount, interval, start_age, end_age ):
        return Withdrawal(
            handle = handle, source_handle = source, amount = amount, interval = interval,
            start_age = start_age, end_age = end_age )

    def _updated_plans( self, plans, entries ):
        return replace( plans, withdrawals = entries )
