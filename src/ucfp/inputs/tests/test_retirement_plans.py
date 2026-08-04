"""The retirement money-movement forms: the shared editable-row base (RetirementMovementForm) and its
three subclasses -- Contributions, Roth conversions, and scheduled withdrawals. All three share one row
shape (account, amount, cadence, age window); the tests pin the deliberate divergences (a contribution's
funding source, the account label, and whether the cadence is optional) and the apply round-trip that
rebuilds each Plans list from a posted row -- which also proves the amount still cleans to a Decimal
through MoneyField."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.parameters import ContributionSource
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.retirement_plans import ContributionsForm, ConversionsForm, WithdrawalsForm

_IRA = ( 'ira', AssetClass.PRETAX_RETIREMENT, 'IRA' )


def _profile( *assets ):
    """A minimal stand-in profile: `(handle, asset_class, name)` assets the row's account picker offers."""
    holdings = [ SimpleNamespace( handle = h, asset_class = k, name = n ) for h, k, n in assets ]
    return SimpleNamespace( assets = holdings )


class PlanRowShapeTests( unittest.TestCase ):
    """The shared row shape, and where the three subclasses legitimately diverge."""

    def test_contributions_row_has_a_source_destination_account_label_and_required_cadence( self ):
        row = ContributionsForm( profile = _profile( _IRA ), plans = Plans() ).plan_rows[ 0 ]
        self.assertIsNotNone( row.get( 'source' ) )            # contributions add a funding source
        self.assertEqual( row[ 'account' ].label, 'Destination account' )   # money flows in
        self.assertFalse( row[ 'cadence_optional' ] )          # always recurring

    def test_conversions_row_has_no_source_from_account_label_and_optional_cadence( self ):
        row = ConversionsForm( profile = _profile( _IRA ), plans = Plans() ).plan_rows[ 0 ]
        self.assertIsNone( row.get( 'source' ) )
        self.assertEqual( row[ 'account' ].label, 'From account' )
        self.assertTrue( row[ 'cadence_optional' ] )           # one-time allowed

    def test_withdrawals_row_matches_the_realization_shape( self ):
        row = WithdrawalsForm( profile = _profile( _IRA ), plans = Plans() ).plan_rows[ 0 ]
        self.assertIsNone( row.get( 'source' ) )
        self.assertEqual( row[ 'account' ].label, 'From account' )
        self.assertTrue( row[ 'cadence_optional' ] )


class ApplyTests( unittest.TestCase ):
    """The apply round-trip: a posted row rebuilds its Plans entry."""

    def test_contribution_round_trips_amount_source_and_a_minted_handle( self ):
        data = QueryDict( mutable = True )
        data[ 'c0_account' ] = 'ira'
        data[ 'c0_amount' ]  = '500'
        data[ 'c0_source' ]  = ContributionSource.PERSONAL.name
        form = ContributionsForm( data, profile = _profile( _IRA ), plans = Plans() )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( len( plans.contributions ), 1 )
        entry = plans.contributions[ 0 ]
        self.assertEqual( entry.amount, Decimal( '500' ) )     # MoneyField cleaned the amount to Decimal
        self.assertEqual( entry.account_handle, 'ira' )
        self.assertEqual( entry.source, ContributionSource.PERSONAL )
        self.assertEqual( entry.handle, 'contribution-1' )     # a stable handle was minted

    def test_withdrawal_with_a_blank_cadence_is_one_time( self ):
        data = QueryDict( mutable = True )
        data[ 'w0_account' ]   = 'ira'
        data[ 'w0_amount' ]    = '10000'
        data[ 'w0_start_age' ] = '60'
        form = WithdrawalsForm( data, profile = _profile( _IRA ), plans = Plans() )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( len( plans.withdrawals ), 1 )
        self.assertIsNone( plans.withdrawals[ 0 ].interval )   # a blank magnitude means one-time

    def test_a_row_without_an_amount_is_not_materialized( self ):
        data = QueryDict( mutable = True )
        data[ 'c0_amount' ] = ''                               # account defaults to the sole account
        form = ContributionsForm( data, profile = _profile( _IRA ), plans = Plans() )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.contributions, [] )            # incomplete row -> skipped


if __name__ == '__main__':
    unittest.main()
