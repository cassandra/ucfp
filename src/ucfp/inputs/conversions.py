"""The Roth conversions table -- the Tax Planning section's conversion ladders (and one-off conversions).

A conversion moves pre-tax retirement money to the owner's Roth. Each is one-time (a single age, no
cadence) or a recurring ladder (every N years over an age window). This presents them as one editable
table -- a row per conversion plus a blank row to add one -- keyed to a stable `conversion-N` handle. The
table auto-saves; validation is non-blocking (an incomplete row simply does not materialize a
conversion). Conversions are a Plans decision, so this form writes only the Plans.
"""
from dataclasses import replace

from django import forms

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.plans.schemas import RothConversion

_PRETAX_CLASS  = AssetClass.PRETAX_RETIREMENT
_MAX_EVERY     = 50
_HANDLE_PREFIX = 'conversion-'


class ConversionsForm( forms.Form ):
    """The Roth conversions table: per row a source pre-tax account, amount, an optional "every N years"
    cadence (blank = one-time), and the age window -- the "From age" alone for a one-time conversion, both
    "From age" and "Until age" for a ladder. `apply` rebuilds `plans.roth_conversions` from the rows (each
    with a stable handle); the Profile is untouched. Non-blocking: a row with no source or no amount is
    skipped."""

    _EXTRA_ROWS = 1

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._accounts    = ( [ asset for asset in profile.assets if asset.asset_class is _PRETAX_CLASS ]
                              if profile is not None else list() )
        self._conversions = list( plans.roth_conversions ) if plans is not None else list()
        self._rows        = len( self._conversions ) + self._EXTRA_ROWS
        for i in range( self._rows ):
            existing = self._conversions[ i ] if i < len( self._conversions ) else None
            self._add_row_fields( i, existing )

    @property
    def has_accounts( self ) -> bool:
        """Whether the household has a pre-tax account to convert from -- else the pane says so rather
        than offering an empty picker."""
        return bool( self._accounts )

    # --- field construction ------------------------------------------------

    def _add_row_fields( self, i : int, conversion ):
        self.fields[ self._key( i, 'source' ) ] = forms.ChoiceField(
            required = False, choices = self._account_choices(),
            initial = conversion.source_handle if conversion is not None else None )
        self.fields[ self._key( i, 'amount' ) ] = forms.DecimalField(
            required = False, min_value = 0,
            initial = conversion.amount if conversion is not None else None )
        self.fields[ self._key( i, 'every' ) ] = forms.IntegerField(
            required = False, min_value = 1, max_value = _MAX_EVERY, initial = self._every( conversion ) )
        self.fields[ self._key( i, 'start_age' ) ] = forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = conversion.start_age if conversion is not None else None )
        self.fields[ self._key( i, 'end_age' ) ] = forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = conversion.end_age if conversion is not None else None )
        if conversion is not None:
            self.fields[ self._key( i, 'handle' ) ] = forms.CharField(
                required = False, widget = forms.HiddenInput, initial = conversion.handle )
            self.fields[ self._key( i, 'remove' ) ] = forms.BooleanField( required = False )

    def _account_choices( self ) -> list:
        candidates = [ ( asset.handle, asset.name ) for asset in self._accounts ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    @staticmethod
    def _every( conversion ):
        return conversion.interval.count if conversion is not None and conversion.interval is not None else None

    @staticmethod
    def _key( index : int, part : str ) -> str:
        return f'v{index}_{part}'

    def _sole_account( self ):
        """The lone pre-tax account when there is only one (its picker has no placeholder, so a blank
        submit still means it); None when several and none was chosen."""
        return self._accounts[ 0 ].handle if len( self._accounts ) == 1 else None

    # --- template rows -----------------------------------------------------

    @property
    def conversion_rows( self ) -> list:
        rows = list()
        for i in range( self._rows ):
            existing = i < len( self._conversions )
            rows.append( {
                'source'    : self[ self._key( i, 'source' ) ],
                'amount'    : self[ self._key( i, 'amount' ) ],
                'every'     : self[ self._key( i, 'every' ) ],
                'start_age' : self[ self._key( i, 'start_age' ) ],
                'end_age'   : self[ self._key( i, 'end_age' ) ],
                'handle'    : self[ self._key( i, 'handle' ) ] if existing else None,
                'remove'    : self[ self._key( i, 'remove' ) ] if existing else None } )
        return rows

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        return profile, replace( plans, roth_conversions = self._rebuilt() )

    def _rebuilt( self ) -> list:
        conversions, taken = list(), { entry.handle for entry in self._conversions }
        for i in range( self._rows ):
            existing = i < len( self._conversions )
            if existing and self.cleaned_data.get( self._key( i, 'remove' ) ):
                continue
            source = self.cleaned_data.get( self._key( i, 'source' ) ) or self._sole_account()
            amount = self.cleaned_data.get( self._key( i, 'amount' ) )
            if not source or amount is None:
                continue                                       # incomplete row -- not materialized
            submitted = self.cleaned_data.get( self._key( i, 'handle' ) )
            handle    = submitted or _minted_conversion_handle( taken )
            taken.add( handle )
            every    = self.cleaned_data.get( self._key( i, 'every' ) )
            interval = Duration( every, TimeUnit.YEAR ) if every else None   # blank = one-time
            conversions.append( RothConversion(
                handle = handle, source_handle = source, amount = amount, interval = interval,
                start_age = self.cleaned_data.get( self._key( i, 'start_age' ) ),
                end_age = self.cleaned_data.get( self._key( i, 'end_age' ) ) ) )
        return conversions


def _minted_conversion_handle( taken : set ) -> str:
    """The lowest `conversion-N` handle free among `taken` -- a conversion row's stable identity, so edits
    round-trip its cadence/window rather than rebuilding it fresh each save."""
    index = 1
    while f'{_HANDLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_HANDLE_PREFIX}{index}'
