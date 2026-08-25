"""The retirement money-movement forms: the shared editable-row base (RetirementMovementForm) and its
three subclasses -- Contributions, Roth conversions, and scheduled withdrawals. All three share one row
shape (account, amount, cadence, age window) as a rowset -- repeated same-name inputs read as parallel
lists; the tests pin the deliberate divergences (a contribution's funding source, the account label, and
whether the cadence is optional) and the apply round-trip that rebuilds each Plans list from a posted row
-- which also proves the amount still cleans to a Decimal through MoneyField."""
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


def _form( form_class, **fields ):
    data = QueryDict( mutable = True )
    for name, value in fields.items():
        data.setlist( name, [ value ] )
    return form_class( data, profile = _profile( _IRA ), plans = Plans() )


class FormShapeTests( unittest.TestCase ):
    """Where the three subclasses legitimately diverge (now form-level flags the shared row reads)."""

    def test_contributions_have_a_source_destination_label_and_required_cadence( self ):
        form = ContributionsForm( profile = _profile( _IRA ), plans = Plans() )
        self.assertTrue( form.has_source )                     # contributions add a funding source
        self.assertEqual( form.account_label, 'Destination account' )   # money flows in
        self.assertFalse( form.cadence_optional )              # always recurring

    def test_conversions_have_no_source_a_from_label_and_optional_cadence( self ):
        form = ConversionsForm( profile = _profile( _IRA ), plans = Plans() )
        self.assertFalse( form.has_source )
        self.assertEqual( form.account_label, 'From account' )
        self.assertTrue( form.cadence_optional )               # one-time allowed

    def test_withdrawals_match_the_realization_shape( self ):
        form = WithdrawalsForm( profile = _profile( _IRA ), plans = Plans() )
        self.assertFalse( form.has_source )
        self.assertEqual( form.account_label, 'From account' )
        self.assertTrue( form.cadence_optional )


class ApplyTests( unittest.TestCase ):
    """The apply round-trip: a posted row rebuilds its Plans entry."""

    def test_contribution_round_trips_amount_source_and_a_minted_handle( self ):
        form = _form( ContributionsForm, c_account = 'ira', c_amount = '500',
                      c_source = ContributionSource.PERSONAL.name )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( len( plans.contributions ), 1 )
        entry = plans.contributions[ 0 ]
        self.assertEqual( entry.amount, Decimal( '500' ) )     # MoneyField cleaned the amount to Decimal
        self.assertEqual( entry.account_handle, 'ira' )
        self.assertEqual( entry.source, ContributionSource.PERSONAL )
        self.assertEqual( entry.handle, 'contribution-1' )     # a stable handle was minted

    def test_a_recurring_contribution_reads_its_cadence( self ):
        form = _form( ContributionsForm, c_account = 'ira', c_amount = '500',
                      c_count = '2', c_unit = 'WEEK' )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        interval = plans.contributions[ 0 ].interval
        self.assertEqual( interval.count, 2 )
        self.assertEqual( interval.unit.name, 'WEEK' )

    def test_withdrawal_with_a_blank_cadence_is_one_time( self ):
        form = _form( WithdrawalsForm, w_account = 'ira', w_amount = '10000', w_start_age = '60' )
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( len( plans.withdrawals ), 1 )
        self.assertIsNone( plans.withdrawals[ 0 ].interval )   # a blank cadence means one-time
        self.assertEqual( plans.withdrawals[ 0 ].start_age, 60 )

    def test_a_row_without_an_amount_is_not_materialized( self ):
        form = _form( ContributionsForm, c_amount = '' )       # account defaults to the sole account
        self.assertTrue( form.is_valid(), form.errors )
        _profile_out, plans = form.apply( None, Plans() )
        self.assertEqual( plans.contributions, [] )            # incomplete row -> skipped

    def test_a_negative_amount_is_a_genuine_error( self ):
        form = _form( ContributionsForm, c_account = 'ira', c_amount = '-5' )
        self.assertFalse( form.is_valid() )
        self.assertIsNotNone( form.rows[ 0 ][ 'error' ] )


if __name__ == '__main__':
    unittest.main()
