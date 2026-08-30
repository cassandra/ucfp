"""The taxable sweep-target account invariant.

The default cash plan sweeps surplus into the Stocks and Bonds accounts, so a forecast cannot build
unless those homes exist. They must be guaranteed for every profile -- not only when the Accounts step
is saved -- or an all-blank / never-visited Accounts step (a valid choice) leaves the profile without
them and the forecast fails with `Sweep destination "stocks" is not a holding`. `_synced_taxable_accounts`
provides the guarantee, wired into `SubjectsForm.apply` (the step every profile goes through) beside the
retirement-account sync.
"""
import unittest
from decimal import Decimal

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.interview import AccountsForm, SubjectsForm, _synced_taxable_accounts
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import AssetProfile, Profile

_TAXABLE_HANDLES = { handle for _field, handle, _cls in AccountsForm._TAXABLE }


class SyncedTaxableAccountsTests( unittest.TestCase ):

    def test_provisions_every_home_at_zero_when_absent( self ):
        accounts = _synced_taxable_accounts( [] )
        self.assertEqual( { a.handle for a in accounts }, _TAXABLE_HANDLES )
        self.assertTrue( all( a.opening_value == Decimal( '0' ) for a in accounts ) )

    def test_preserves_a_funded_home_and_keeps_non_taxable_assets( self ):
        existing = [
            AssetProfile( handle = 'stocks', name = 'Stocks',
                          asset_class = AssetClass.STOCKS, opening_value = Decimal( '1000' ) ),
            AssetProfile( handle = 'ira', name = 'IRA',
                          asset_class = AssetClass.PRETAX_RETIREMENT, opening_value = Decimal( '500' ) ) ]
        by_handle = { a.handle : a for a in _synced_taxable_accounts( existing ) }
        self.assertEqual( by_handle[ 'stocks' ].opening_value, Decimal( '1000' ) )   # funded -> preserved
        self.assertEqual( by_handle[ 'bonds' ].opening_value, Decimal( '0' ) )       # absent -> provisioned
        self.assertIn( 'ira', by_handle )                                            # non-taxable kept


class SubjectsApplyInvariantTests( unittest.TestCase ):

    def test_saving_subjects_provisions_the_sweep_target_homes( self ):
        # The regression: with a blank Accounts step, saving Subjects must still leave the profile with
        # the Stocks/Bonds homes the default sweep needs.
        data = QueryDict( mutable = True )
        data[ 'subject_name' ]      = 'Alice'
        data[ 'subject_birthdate' ] = '1970-01'
        form = SubjectsForm( data, profile = Profile(), plans = Plans() )
        self.assertTrue( form.is_valid(), form.errors )
        updated, _plans = form.apply( Profile(), Plans() )
        handles = { a.handle for a in updated.assets }
        self.assertIn( 'stocks', handles )
        self.assertIn( 'bonds', handles )


if __name__ == '__main__':
    unittest.main()
