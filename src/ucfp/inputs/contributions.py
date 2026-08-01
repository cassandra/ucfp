"""The retirement contributions table -- the saving side of the Retirement section.

A recurring contribution is a per-occurrence amount at a chosen cadence into a retirement account, over
an optional age window (the account owner's age). This presents them as one editable table -- a row per
contribution plus a blank row to add one -- keyed to a stable `contribution-N` handle. The table
auto-saves; validation is non-blocking (an incomplete row simply does not materialize a contribution).
Contributions are a Plans decision, so this form writes only the Plans.
"""
from dataclasses import replace

from django import forms

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.parameters import ContributionSource
from ucfp.inputs.cadence import add_cadence_fields, cadence_cells, read_cadence
from ucfp.inputs.plans.schemas import Contribution
from ucfp.parameter_sets.enums import CadenceDomain

_RETIREMENT_CLASSES  = ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH )
_CONTRIBUTION_DOMAIN = CadenceDomain.MO_YR                  # contributions recur monthly or annually
_DEFAULT_INTERVAL    = Duration( 1, TimeUnit.MONTH )
_HANDLE_PREFIX       = 'contribution-'


class ContributionsForm( forms.Form ):
    """The recurring-contributions table: per row an account, amount, cadence, source, and an optional
    start/end age (the account owner's), with a blank row to add one. `apply` rebuilds
    `plans.contributions` from the rows (each with a stable handle); the Profile is untouched.
    Non-blocking: a row with no account or no amount is skipped."""

    _EXTRA_ROWS = 1

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._accounts      = ( [ asset for asset in profile.assets
                                  if asset.asset_class in _RETIREMENT_CLASSES ]
                                if profile is not None else list() )
        self._contributions = list( plans.contributions ) if plans is not None else list()
        self._rows          = len( self._contributions ) + self._EXTRA_ROWS
        for i in range( self._rows ):
            existing = self._contributions[ i ] if i < len( self._contributions ) else None
            self._add_row_fields( i, existing )

    @property
    def has_accounts( self ) -> bool:
        """Whether the household has a retirement account to contribute to -- else the pane says so
        rather than offering an empty account picker."""
        return bool( self._accounts )

    # --- field construction ------------------------------------------------

    def _add_row_fields( self, i : int, contribution ):
        self.fields[ self._key( i, 'account' ) ] = forms.ChoiceField(
            required = False, choices = self._account_choices(),
            initial = contribution.account_handle if contribution is not None else None )
        self.fields[ self._key( i, 'amount' ) ] = forms.DecimalField(
            required = False, min_value = 0,
            initial = contribution.amount if contribution is not None else None )
        self.fields[ self._key( i, 'source' ) ] = forms.ChoiceField(
            required = False, choices = self._source_choices(),
            initial = ( contribution.source if contribution is not None
                        else ContributionSource.PERSONAL ).name )
        self.fields[ self._key( i, 'start_age' ) ] = forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = contribution.start_age if contribution is not None else None )
        self.fields[ self._key( i, 'end_age' ) ] = forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = contribution.end_age if contribution is not None else None )
        add_cadence_fields( self, self._cadence( i ), self._interval( contribution ), _CONTRIBUTION_DOMAIN )
        if contribution is not None:
            self.fields[ self._key( i, 'handle' ) ] = forms.CharField(
                required = False, widget = forms.HiddenInput, initial = contribution.handle )
            self.fields[ self._key( i, 'remove' ) ] = forms.BooleanField( required = False )

    def _account_choices( self ) -> list:
        candidates = [ ( asset.handle, asset.name ) for asset in self._accounts ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    @staticmethod
    def _source_choices() -> list:
        return [ ( source.name, source.label ) for source in ContributionSource ]

    @staticmethod
    def _interval( contribution ) -> Duration:
        return contribution.interval if contribution is not None else _DEFAULT_INTERVAL

    @staticmethod
    def _key( index : int, part : str ) -> str:
        return f'c{index}_{part}'

    @staticmethod
    def _cadence( index : int ) -> str:
        return f'c{index}_cad'

    def _sole_account( self ):
        """The lone retirement account when there is only one (its picker has no placeholder, so a blank
        submit still means it); None when several and none was chosen."""
        return self._accounts[ 0 ].handle if len( self._accounts ) == 1 else None

    # --- template rows -----------------------------------------------------

    @property
    def contribution_rows( self ) -> list:
        rows = list()
        for i in range( self._rows ):
            existing = i < len( self._contributions )
            rows.append( {
                'account'   : self[ self._key( i, 'account' ) ],
                'amount'    : self[ self._key( i, 'amount' ) ],
                'source'    : self[ self._key( i, 'source' ) ],
                'start_age' : self[ self._key( i, 'start_age' ) ],
                'end_age'   : self[ self._key( i, 'end_age' ) ],
                'cadence'   : cadence_cells(
                    self, self._cadence( i ),
                    self._interval( self._contributions[ i ] if existing else None ), _CONTRIBUTION_DOMAIN ),
                'handle'    : self[ self._key( i, 'handle' ) ] if existing else None,
                'remove'    : self[ self._key( i, 'remove' ) ] if existing else None } )
        return rows

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        return profile, replace( plans, contributions = self._rebuilt() )

    def _rebuilt( self ) -> list:
        contributions, taken = list(), { entry.handle for entry in self._contributions }
        for i in range( self._rows ):
            existing = i < len( self._contributions )
            if existing and self.cleaned_data.get( self._key( i, 'remove' ) ):
                continue
            account = self.cleaned_data.get( self._key( i, 'account' ) ) or self._sole_account()
            amount  = self.cleaned_data.get( self._key( i, 'amount' ) )
            if not account or amount is None:
                continue                                       # incomplete row -- not materialized
            submitted = self.cleaned_data.get( self._key( i, 'handle' ) )
            handle    = submitted or _minted_contribution_handle( taken )
            taken.add( handle )
            seed = self._interval( self._contributions[ i ] if existing else None )
            contributions.append( Contribution(
                handle = handle, account_handle = account, amount = amount,
                source = self._source( i ),
                interval = read_cadence( self, self._cadence( i ), seed, _CONTRIBUTION_DOMAIN ),
                start_age = self.cleaned_data.get( self._key( i, 'start_age' ) ),
                end_age = self.cleaned_data.get( self._key( i, 'end_age' ) ) ) )
        return contributions

    def _source( self, i : int ) -> ContributionSource:
        chosen = self.cleaned_data.get( self._key( i, 'source' ) ) or ContributionSource.PERSONAL.name
        return ContributionSource[ chosen ]


def _minted_contribution_handle( taken : set ) -> str:
    """The lowest `contribution-N` handle free among `taken` -- a contribution row's stable identity, so
    edits round-trip its cadence/window rather than rebuilding it fresh each save."""
    index = 1
    while f'{_HANDLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_HANDLE_PREFIX}{index}'
