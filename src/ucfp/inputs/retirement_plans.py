"""Retirement money-movement tables -- contributions, Roth conversions, and scheduled withdrawals.

All three are the same editable table: a row per planned movement of a retirement account -- the account,
an amount, a cadence, and an age window (the account owner's) -- plus a blank add-row, each keyed to a
stable minted handle; non-blocking (an incomplete row does not materialize). `RetirementMovementForm`
holds the shared table; each subclass supplies its source account classes, handle/field prefixes, whether
the cadence is optional (a one-time entry allowed) and its default, and the Plans list + entry type it
reads and writes, and may add extra per-row fields (a contribution's funding source). All write only the
Plans.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.parameters import ContributionSource
from ucfp.inputs.cadence import (
    add_cadence_fields, add_optional_cadence_fields, cadence_cells, read_cadence, read_optional_cadence )
from ucfp.inputs.plans.schemas import Contribution, RothConversion, Withdrawal
from ucfp.parameter_sets.enums import CadenceDomain

_PRETAX             = AssetClass.PRETAX_RETIREMENT
_RETIREMENT_CLASSES = ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH )
_CADENCE_DOMAIN     = CadenceDomain.WK_MO_YR   # weekly (per-paycheck), monthly, or yearly


class RetirementMovementForm( forms.Form ):
    """Shared base for a retirement money-movement table: a row per entry -- an account, amount, cadence,
    and age window -- plus a blank add-row, each keyed to a stable handle; non-blocking (a row with no
    account or amount is skipped). `apply` rebuilds the subclass's Plans list. A subclass sets
    `_ACCOUNT_CLASSES`, `_HANDLE_PREFIX`, `_KEY_PREFIX`, whether the cadence is optional
    (`_CADENCE_OPTIONAL` -- a blank magnitude then means one-time) and its default (`_DEFAULT_INTERVAL`),
    implements the account/entry/plans hooks, and may add extra per-row fields."""

    _EXTRA_ROWS       = 1
    _ACCOUNT_CLASSES  = ()          # subclass: the valid source asset classes
    _HANDLE_PREFIX    = ''          # subclass: minted handle prefix (e.g. 'contribution-')
    _KEY_PREFIX       = ''          # subclass: field-name namespace (e.g. 'c')
    _CADENCE_OPTIONAL = False       # subclass: True lets a row be one-time (blank cadence)
    _DEFAULT_INTERVAL = None        # subclass: the seeded cadence for a required-cadence blank row

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
        """The subclass's current Plans list (e.g. `plans.contributions`)."""
        raise NotImplementedError

    def _entry_account( self, entry ) -> str:
        """The account handle an entry names -- `account_handle` for a contribution, `source_handle` for a
        realization."""
        raise NotImplementedError

    def _build_entry( self, i, handle, account, amount, interval, start_age, end_age ):
        """The subclass's Plans entry from a row's values (row index `i`, so it can read its own extra
        fields)."""
        raise NotImplementedError

    def _updated_plans( self, plans, entries ):
        """`plans` with the rebuilt entries stored on the subclass's field."""
        raise NotImplementedError

    def _add_extra_fields( self, i, entry ) -> None:
        """Add any per-row fields beyond the common ones (a contribution's funding source). None by
        default."""
        return None

    def _extra_row( self, i ) -> dict:
        """Any extra bound fields for the template row, merged into the common ones. None by default."""
        return dict()

    @property
    def has_accounts( self ) -> bool:
        """Whether the household has an account of the right kind -- else the pane says so rather than
        offering an empty picker."""
        return bool( self._accounts )

    # --- field construction ------------------------------------------------

    def _add_row_fields( self, i : int, entry ):
        self.fields[ self._key( i, 'account' ) ] = forms.ChoiceField(
            label = 'Account', required = False, choices = self._account_choices(),
            initial = self._entry_account( entry ) if entry is not None else None )
        self.fields[ self._key( i, 'amount' ) ] = MoneyField(
            label = 'Amount', required = False, min_value = 0,
            initial = entry.amount if entry is not None else None )
        self._add_cadence( i, entry )
        self._add_extra_fields( i, entry )
        self.fields[ self._key( i, 'start_age' ) ] = forms.IntegerField(
            label = 'From age', required = False, min_value = 0, max_value = 120,
            initial = entry.start_age if entry is not None else None )
        self.fields[ self._key( i, 'end_age' ) ] = forms.IntegerField(
            label = 'Until age', required = False, min_value = 0, max_value = 120,
            initial = entry.end_age if entry is not None else None )
        if entry is not None:
            self.fields[ self._key( i, 'handle' ) ] = forms.CharField(
                required = False, widget = forms.HiddenInput, initial = entry.handle )
            self.fields[ self._key( i, 'remove' ) ] = forms.BooleanField( required = False )

    def _add_cadence( self, i : int, entry ):
        interval = entry.interval if entry is not None else None
        if self._CADENCE_OPTIONAL:
            add_optional_cadence_fields( self, self._cadence( i ), interval, _CADENCE_DOMAIN )
        else:
            add_cadence_fields(
                self, self._cadence( i ), interval or self._DEFAULT_INTERVAL, _CADENCE_DOMAIN )

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
        """The lone account when there is only one (its picker has no placeholder, so a blank submit still
        means it); None when several and none was chosen."""
        return self._accounts[ 0 ].handle if len( self._accounts ) == 1 else None

    # --- template rows -----------------------------------------------------

    @property
    def plan_rows( self ) -> list:
        rows = list()
        for i in range( self._rows ):
            existing = i < len( self._entries )
            interval = self._entries[ i ].interval if existing else None
            row = {
                'account'   : self[ self._key( i, 'account' ) ],
                'amount'    : self[ self._key( i, 'amount' ) ],
                'cadence'   : cadence_cells( self, self._cadence( i ), interval, _CADENCE_DOMAIN ),
                'start_age' : self[ self._key( i, 'start_age' ) ],
                'end_age'   : self[ self._key( i, 'end_age' ) ],
                'handle'    : self[ self._key( i, 'handle' ) ] if existing else None,
                'remove'    : self[ self._key( i, 'remove' ) ] if existing else None }
            row.update( self._extra_row( i ) )
            rows.append( row )
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
            account = self.cleaned_data.get( self._key( i, 'account' ) ) or self._sole_account()
            amount  = self.cleaned_data.get( self._key( i, 'amount' ) )
            if not account or amount is None:
                continue                                       # incomplete row -- not materialized
            submitted = self.cleaned_data.get( self._key( i, 'handle' ) )
            handle    = submitted or self._minted_handle( taken )
            taken.add( handle )
            entries.append( self._build_entry(
                i, handle, account, amount, self._read_interval( i, existing ),
                self.cleaned_data.get( self._key( i, 'start_age' ) ),
                self.cleaned_data.get( self._key( i, 'end_age' ) ) ) )
            continue
        return entries

    def _read_interval( self, i : int, existing : bool ):
        if self._CADENCE_OPTIONAL:
            return read_optional_cadence( self, self._cadence( i ), _CADENCE_DOMAIN )
        seed = self._entries[ i ].interval if existing else self._DEFAULT_INTERVAL
        return read_cadence( self, self._cadence( i ), seed, _CADENCE_DOMAIN )

    def _minted_handle( self, taken : set ) -> str:
        """The lowest `{prefix}N` handle free among `taken` -- a row's stable identity, so edits round-trip
        its cadence/window rather than rebuilding it fresh each save."""
        index = 1
        while f'{self._HANDLE_PREFIX}{index}' in taken:
            index += 1
        return f'{self._HANDLE_PREFIX}{index}'


class ContributionsForm( RetirementMovementForm ):
    """Recurring retirement contributions into a retirement account, with a funding source (which sets the
    tax treatment and the annual limit). Always recurring -- the cadence is required."""

    _ACCOUNT_CLASSES  = _RETIREMENT_CLASSES
    _HANDLE_PREFIX    = 'contribution-'
    _KEY_PREFIX       = 'c'
    _DEFAULT_INTERVAL = Duration( 1, TimeUnit.MONTH )

    def _plan_entries( self, plans ) -> list:
        return plans.contributions

    def _entry_account( self, entry ) -> str:
        return entry.account_handle

    def _add_extra_fields( self, i, entry ) -> None:
        self.fields[ self._key( i, 'source' ) ] = forms.ChoiceField(
            label = 'Source', required = False,
            choices = [ ( source.name, source.label ) for source in ContributionSource ],
            initial = ( entry.source if entry is not None else ContributionSource.PERSONAL ).name )

    def _extra_row( self, i ) -> dict:
        return { 'source' : self[ self._key( i, 'source' ) ] }

    def _build_entry( self, i, handle, account, amount, interval, start_age, end_age ):
        chosen = self.cleaned_data.get( self._key( i, 'source' ) ) or ContributionSource.PERSONAL.name
        return Contribution(
            handle = handle, account_handle = account, amount = amount,
            source = ContributionSource[ chosen ], interval = interval,
            start_age = start_age, end_age = end_age )

    def _updated_plans( self, plans, entries ):
        return replace( plans, contributions = entries )


class ConversionsForm( RetirementMovementForm ):
    """Roth conversions: move pre-tax retirement money to the owner's Roth (resolved at materialize).
    One-time (a single age) or a recurring ladder."""

    _ACCOUNT_CLASSES  = ( _PRETAX, )
    _HANDLE_PREFIX    = 'conversion-'
    _KEY_PREFIX       = 'v'
    _CADENCE_OPTIONAL = True

    def _plan_entries( self, plans ) -> list:
        return plans.roth_conversions

    def _entry_account( self, entry ) -> str:
        return entry.source_handle

    def _build_entry( self, i, handle, account, amount, interval, start_age, end_age ):
        return RothConversion(
            handle = handle, source_handle = account, amount = amount, interval = interval,
            start_age = start_age, end_age = end_age )

    def _updated_plans( self, plans, entries ):
        return replace( plans, roth_conversions = entries )


class WithdrawalsForm( RetirementMovementForm ):
    """Pre-tax account withdrawals: deliberate draws from a pre-tax retirement account to cash (a tax
    lever -- the draw is ordinary income). One-time or recurring."""

    _ACCOUNT_CLASSES  = ( _PRETAX, )
    _HANDLE_PREFIX    = 'withdrawal-'
    _KEY_PREFIX       = 'w'
    _CADENCE_OPTIONAL = True

    def _plan_entries( self, plans ) -> list:
        return plans.withdrawals

    def _entry_account( self, entry ) -> str:
        return entry.source_handle

    def _build_entry( self, i, handle, account, amount, interval, start_age, end_age ):
        return Withdrawal(
            handle = handle, source_handle = account, amount = amount, interval = interval,
            start_age = start_age, end_age = end_age )

    def _updated_plans( self, plans, entries ):
        return replace( plans, withdrawals = entries )
