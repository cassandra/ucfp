"""Retirement money-movement tables -- contributions, Roth conversions, and scheduled withdrawals.

All three are the same editable table: a row per planned movement of a retirement account -- the account,
an amount, a cadence, and an age window (the account owner's) -- each keyed to a stable minted handle;
non-blocking (an incomplete row does not materialize). The rows are a rowset: repeated same-name inputs the
form reads as parallel lists (getlist), added and removed client-side (`js-rowset`, inputs.js), rather than
through a phantom trailing block. `RetirementMovementForm` holds the shared table; each subclass supplies
its source account classes, handle/field prefixes, whether the cadence is optional (a one-time entry
allowed) and its default, and the Plans list + entry type it reads and writes, and may add a funding
source (contributions). All write only the Plans.
"""
from dataclasses import replace
from itertools import zip_longest

from django import forms

from common.forms import MoneyField
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.parameters import ContributionSource
from ucfp.inputs.cadence import cadence_units
from ucfp.inputs.plans.schemas import Contribution, RothConversion, Withdrawal
from ucfp.parameter_sets.enums import CadenceDomain

_PRETAX             = AssetClass.PRETAX_RETIREMENT
_RETIREMENT_CLASSES = ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH )
_CADENCE_DOMAIN     = CadenceDomain.WK_MO_YR   # weekly (per-paycheck), monthly, or yearly
_MAX_PLAN_AGE       = 120                      # a plan age above this is implausible; treated as unset


class RetirementMovementForm( forms.Form ):
    """Shared base for a retirement money-movement rowset: a row per entry -- an account, amount, cadence,
    and age window -- each keyed to a stable handle; non-blocking (a row with no account or amount is
    skipped). `apply` rebuilds the subclass's Plans list. A subclass sets `_ACCOUNT_CLASSES`,
    `_HANDLE_PREFIX`, `_KEY_PREFIX`, whether the cadence is optional (`_CADENCE_OPTIONAL` -- a blank cadence
    then means one-time) and its default (`_DEFAULT_INTERVAL`), whether a funding source applies
    (`_HAS_SOURCE`), and implements the account/entry/plans hooks."""

    _ACCOUNT_CLASSES  = ()          # subclass: the valid source asset classes
    _ACCOUNT_LABEL    = 'Account'   # subclass: the account picker's label (e.g. 'From account')
    _HANDLE_PREFIX    = ''          # subclass: minted handle prefix (e.g. 'contribution-')
    _KEY_PREFIX       = ''          # subclass: field-name namespace (e.g. 'c'), so two panes coexist
    _CADENCE_OPTIONAL = False       # subclass: True lets a row be one-time (blank cadence)
    _DEFAULT_INTERVAL = None        # subclass: the seeded cadence for a required-cadence row
    _HAS_SOURCE       = False       # subclass: True adds a funding-source select (contributions)

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._accounts = ( [ asset for asset in profile.assets
                             if asset.asset_class in self._ACCOUNT_CLASSES ]
                           if profile is not None else list() )
        self._entries  = list( self._plan_entries( plans ) ) if plans is not None else list()
        self._amount_field = MoneyField( required = False, min_value = 0 )   # reused to parse rowset amounts
        self._row_errors   = dict()                    # rowset index -> amount error message (set in clean)

    # --- subclass hooks ----------------------------------------------------

    def _plan_entries( self, plans ) -> list:
        """The subclass's current Plans list (e.g. `plans.contributions`)."""
        raise NotImplementedError

    def _entry_account( self, entry ) -> str:
        """The account handle an entry names -- `account_handle` for a contribution, `source_handle` for a
        realization."""
        raise NotImplementedError

    def _entry_source( self, entry ) -> str:
        """The funding-source value an entry carries, for the source select's initial -- '' when the
        subclass has no source."""
        return ''

    def _build_entry( self, handle, account, amount, interval, start_age, end_age, source ):
        """The subclass's Plans entry from a row's values."""
        raise NotImplementedError

    def _updated_plans( self, plans, entries ):
        """`plans` with the rebuilt entries stored on the subclass's field."""
        raise NotImplementedError

    # --- names, choices, flags (for the template) --------------------------

    def _name( self, part : str ) -> str:
        return f'{self._KEY_PREFIX}_{part}'

    @property
    def names( self ) -> dict:
        """The rowset field names -- one source shared with the row template's inputs and the getlist keys.
        Namespaced by `_KEY_PREFIX` so the two Tax Planning panes' forms do not collide on one page."""
        return { 'account' : self._name( 'account' ), 'source' : self._name( 'source' ),
                 'count' : self._name( 'count' ), 'unit' : self._name( 'unit' ),
                 'amount' : self._name( 'amount' ), 'handle' : self._name( 'handle' ),
                 'start_age' : self._name( 'start_age' ), 'end_age' : self._name( 'end_age' ) }

    @property
    def account_label( self ) -> str:
        return self._ACCOUNT_LABEL

    @property
    def has_source( self ) -> bool:
        return self._HAS_SOURCE

    @property
    def cadence_optional( self ) -> bool:
        return self._CADENCE_OPTIONAL

    @property
    def account_choices( self ) -> list:
        candidates = [ ( asset.handle, asset.name ) for asset in self._accounts ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    @property
    def source_choices( self ) -> list:
        return [ ( source.name, source.label ) for source in ContributionSource ] if self._HAS_SOURCE else []

    @property
    def unit_choices( self ) -> list:
        return [ ( unit.name, unit.label ) for unit in cadence_units( _CADENCE_DOMAIN ) ]

    @property
    def has_accounts( self ) -> bool:
        """Whether the household has an account of the right kind -- else the pane says so rather than
        offering an empty picker."""
        return bool( self._accounts )

    def _sole_account( self ):
        """The lone account when there is only one (its picker has no placeholder, so a blank submit still
        means it); None when several and none was chosen."""
        return self._accounts[ 0 ].handle if len( self._accounts ) == 1 else None

    # --- rows --------------------------------------------------------------

    def _posted( self ):
        """The posted rows as tuples, zipped by position -- one per rendered rowset row (the blank
        <template> prototype is inert, so it never posts)."""
        n = self.names
        return zip_longest(
            self.data.getlist( n[ 'account' ] ), self.data.getlist( n[ 'amount' ] ),
            self.data.getlist( n[ 'count' ] ), self.data.getlist( n[ 'unit' ] ),
            self.data.getlist( n[ 'start_age' ] ), self.data.getlist( n[ 'end_age' ] ),
            self.data.getlist( n[ 'handle' ] ), self.data.getlist( n[ 'source' ] ), fillvalue = '' )

    @property
    def rows( self ) -> list:
        """The rows for the rowset. Bound (a re-render after an edit): the submitted values, so typing
        survives an error re-render, each with any amount error. Unbound (first load): the stored entries."""
        if self.is_bound:
            return [ { 'account' : acct, 'amount' : amt, 'count' : cnt, 'unit' : unit,
                       'start_age' : start, 'end_age' : end, 'handle' : handle, 'source' : source,
                       'error' : self._row_errors.get( i ) }
                     for i, ( acct, amt, cnt, unit, start, end, handle, source ) in enumerate( self._posted() ) ]
        rows = list()
        for entry in self._entries:
            interval = entry.interval
            rows.append( {
                'account' : self._entry_account( entry ), 'amount' : entry.amount,
                'count'   : interval.count if interval is not None else '',
                'unit'    : interval.unit.name if interval is not None else '',
                'start_age' : entry.start_age, 'end_age' : entry.end_age,
                'handle'  : entry.handle, 'source' : self._entry_source( entry ), 'error' : None } )
        return rows

    # --- validation & parsing ----------------------------------------------

    def clean( self ):
        """Surface a negative amount as a genuine error (so the pane re-renders it), keyed to its row for
        the template; a blank or otherwise-incomplete row stays non-blocking."""
        cleaned = super().clean()
        for i, ( _acct, amt, *_rest ) in enumerate( self._posted() ):
            if not amt:
                continue
            try:
                self._amount_field.clean( amt )
            except forms.ValidationError as error:
                self._row_errors[ i ] = ' '.join( error.messages )
        if self._row_errors:
            raise forms.ValidationError( 'Check the highlighted amounts.' )
        return cleaned

    def _parse_amount( self, raw : str ):
        try:
            return self._amount_field.clean( raw )
        except forms.ValidationError:
            return None

    @staticmethod
    def _parse_age( raw : str ):
        """A posted age as an int in [0, 120], else None -- blank, non-numeric (negatives fail `isdigit`),
        or an implausible age is treated as unset rather than materialized, the non-blocking equivalent of
        the declared field's old `max_value=120` (kept through the getlist migration)."""
        if not ( raw and raw.strip().isdigit() ):
            return None
        age = int( raw.strip() )
        return age if age <= _MAX_PLAN_AGE else None

    def _read_interval( self, count_raw : str, unit_raw : str ):
        """The row's cadence as a Duration: the chosen magnitude/unit, else -- for an optional cadence -- a
        blank magnitude means one-time (None); a required cadence falls back to its default."""
        if self._CADENCE_OPTIONAL and not count_raw.strip():
            return None
        units = cadence_units( _CADENCE_DOMAIN )
        count = int( count_raw ) if count_raw.strip().isdigit() else (
            self._DEFAULT_INTERVAL.count if self._DEFAULT_INTERVAL is not None else 1 )
        unit  = TimeUnit[ unit_raw ] if unit_raw in TimeUnit.__members__ else (
            self._DEFAULT_INTERVAL.unit if self._DEFAULT_INTERVAL is not None else units[ 0 ] )
        return Duration( count, unit )

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        return profile, self._updated_plans( plans, self._rebuilt() )

    def _rebuilt( self ) -> list:
        taken   = { handle for handle in self.data.getlist( self.names[ 'handle' ] ) if handle }
        entries = list()
        for acct, amt, cnt, unit, start, end, handle_raw, source in self._posted():
            account = acct or self._sole_account()
            amount  = self._parse_amount( amt )
            if not account or amount is None:
                continue                                       # incomplete row -- not materialized
            handle = handle_raw or self._minted_handle( taken )
            taken.add( handle )
            entries.append( self._build_entry(
                handle, account, amount, self._read_interval( cnt, unit ),
                self._parse_age( start ), self._parse_age( end ), source ) )
        return entries

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
    _ACCOUNT_LABEL    = 'Destination account'   # money flows in, so name the account by its role
    _HANDLE_PREFIX    = 'contribution-'
    _KEY_PREFIX       = 'c'
    _DEFAULT_INTERVAL = Duration( 1, TimeUnit.MONTH )
    _HAS_SOURCE       = True

    def _plan_entries( self, plans ) -> list:
        return plans.contributions

    def _entry_account( self, entry ) -> str:
        return entry.account_handle

    def _entry_source( self, entry ) -> str:
        return entry.source.name

    def _build_entry( self, handle, account, amount, interval, start_age, end_age, source ):
        chosen = source if source in ContributionSource.__members__ else ContributionSource.PERSONAL.name
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
    _ACCOUNT_LABEL    = 'From account'
    _HANDLE_PREFIX    = 'conversion-'
    _KEY_PREFIX       = 'v'
    _CADENCE_OPTIONAL = True

    def _plan_entries( self, plans ) -> list:
        return plans.roth_conversions

    def _entry_account( self, entry ) -> str:
        return entry.source_handle

    def _build_entry( self, handle, account, amount, interval, start_age, end_age, source ):
        return RothConversion(
            handle = handle, source_handle = account, amount = amount, interval = interval,
            start_age = start_age, end_age = end_age )

    def _updated_plans( self, plans, entries ):
        return replace( plans, roth_conversions = entries )


class WithdrawalsForm( RetirementMovementForm ):
    """Pre-tax account withdrawals: deliberate draws from a pre-tax retirement account to cash (a tax
    lever -- the draw is ordinary income). One-time or recurring."""

    _ACCOUNT_CLASSES  = ( _PRETAX, )
    _ACCOUNT_LABEL    = 'From account'
    _HANDLE_PREFIX    = 'withdrawal-'
    _KEY_PREFIX       = 'w'
    _CADENCE_OPTIONAL = True

    def _plan_entries( self, plans ) -> list:
        return plans.withdrawals

    def _entry_account( self, entry ) -> str:
        return entry.source_handle

    def _build_entry( self, handle, account, amount, interval, start_age, end_age, source ):
        return Withdrawal(
            handle = handle, source_handle = account, amount = amount, interval = interval,
            start_age = start_age, end_age = end_age )

    def _updated_plans( self, plans, entries ):
        return replace( plans, withdrawals = entries )
