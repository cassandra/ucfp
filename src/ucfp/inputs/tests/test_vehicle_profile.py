"""VehicleHoldingForm: an owned vehicle round-trips as a DEPRECIATING holding plus an optional auto loan.

The value earning a test here is the holding + secured-debt write (the same shape a mortgaged property
uses, with a loan in place of the mortgage): a complete vehicle materializes as a `DEPRECIATING`
`AssetProfile`, a balance auto-creates an `AUTO` `Debt` secured against it (`{handle}-loan`), an edit
pre-fills and preserves a name/kind the Debts section may have set, and clearing the balance drops the
debt. Non-blocking materialization (a half-entered vehicle writes nothing) and the section listing round
it out. The delete reap is `delete_property`'s, exercised through the vehicle's secured loan here.
"""
import unittest
from decimal import Decimal

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.interview import VehiclesForm
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile
from ucfp.inputs.properties import delete_property
from ucfp.inputs.vehicle_profile import VehicleHoldingForm


def _apply( profile : Profile, handle = None, **fields ):
    """Submit the given vehicle fields over an existing profile and return the resulting profile."""
    data = QueryDict( mutable = True )
    data.update( fields )
    form = VehicleHoldingForm( data, profile = profile, plans = Plans(), handle = handle )
    assert form.is_valid(), form.errors
    result, _plans = form.apply( profile, Plans() )
    return result


def _vehicle( handle, name, value ) -> AssetProfile:
    return AssetProfile( handle = handle, name = name, asset_class = AssetClass.DEPRECIATING,
                         opening_value = Decimal( value ) )


class VehicleHoldingTests( unittest.TestCase ):

    def test_a_complete_vehicle_writes_a_depreciating_holding( self ):
        result = _apply( Profile(), name = 'Car', value = '30,000' )
        self.assertEqual( len( result.assets ), 1 )
        car = result.assets[ 0 ]
        self.assertEqual( car.handle, 'vehicle-1' )                 # minted, lowest free
        self.assertEqual( car.asset_class, AssetClass.DEPRECIATING )
        self.assertEqual( car.opening_value, Decimal( '30000' ) )
        self.assertIsNone( car.cost_basis )                        # a vehicle's sale is tax-free
        self.assertEqual( result.debts, [] )                       # no balance -> no loan

    def test_a_half_entered_vehicle_writes_nothing( self ):
        # Name without a value is incomplete; materialization is non-blocking, so nothing is written.
        result = _apply( Profile(), name = 'Car' )
        self.assertEqual( result.assets, [] )

    def test_a_loan_balance_creates_a_secured_auto_loan( self ):
        result = _apply( Profile(), handle = 'vehicle-1', name = 'Car', value = '30,000',
                         loan_balance = '18,000' )
        self.assertEqual( len( result.debts ), 1 )
        loan = result.debts[ 0 ]
        self.assertEqual( loan.handle, 'vehicle-1-loan' )
        self.assertEqual( loan.kind, DebtKind.AUTO )
        self.assertEqual( loan.balance, Decimal( '18000' ) )
        self.assertEqual( loan.secured_asset, 'vehicle-1' )
        self.assertEqual( loan.name, 'Car Loan' )

    def test_an_edit_preserves_a_loan_name_and_kind_set_in_debts( self ):
        # The vehicle is a balance-only surface onto the one debt; a name/kind the Debts section chose
        # survives an edit here (only the balance is this form's to own).
        profile = Profile(
            assets = [ _vehicle( 'vehicle-1', 'Car', '30000' ) ],
            debts  = [ Debt( handle = 'vehicle-1-loan', name = 'Credit Union Auto', kind = DebtKind.OTHER,
                             balance = Decimal( '18000' ), secured_asset = 'vehicle-1' ) ] )
        result = _apply( profile, handle = 'vehicle-1', name = 'Car', value = '31,000',
                         loan_balance = '17,000' )
        loan = result.debts[ 0 ]
        self.assertEqual( ( loan.name, loan.kind ), ( 'Credit Union Auto', DebtKind.OTHER ) )
        self.assertEqual( loan.balance, Decimal( '17000' ) )       # the balance is updated

    def test_clearing_the_balance_drops_the_loan( self ):
        profile = Profile(
            assets = [ _vehicle( 'vehicle-1', 'Car', '30000' ) ],
            debts  = [ Debt( handle = 'vehicle-1-loan', name = 'Car Loan', kind = DebtKind.AUTO,
                             balance = Decimal( '18000' ), secured_asset = 'vehicle-1' ) ] )
        result = _apply( profile, handle = 'vehicle-1', name = 'Car', value = '30,000' )   # balance blank
        self.assertEqual( result.debts, [] )

    def test_edit_pre_fills_name_value_and_loan_balance( self ):
        profile = Profile(
            assets = [ _vehicle( 'vehicle-1', 'Car', '30000' ) ],
            debts  = [ Debt( handle = 'vehicle-1-loan', name = 'Car Loan', kind = DebtKind.AUTO,
                             balance = Decimal( '18000' ), secured_asset = 'vehicle-1' ) ] )
        form = VehicleHoldingForm( profile = profile, plans = Plans(), handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'name' ], 'Car' )
        self.assertEqual( form.initial[ 'value' ], Decimal( '30000' ) )
        self.assertEqual( form.initial[ 'loan_balance' ], Decimal( '18000' ) )

    def test_deleting_a_vehicle_reaps_its_secured_loan( self ):
        profile = Profile(
            assets = [ _vehicle( 'vehicle-1', 'Car', '30000' ) ],
            debts  = [ Debt( handle = 'vehicle-1-loan', name = 'Car Loan', kind = DebtKind.AUTO,
                             balance = Decimal( '18000' ), secured_asset = 'vehicle-1' ) ] )
        result, _plans = delete_property( profile, Plans(), 'vehicle-1' )
        self.assertEqual( ( result.assets, result.debts ), ( [], [] ) )


class VehiclesSectionTests( unittest.TestCase ):
    """The section pane lists the household's current vehicles -- the DEPRECIATING holdings -- and not
    other asset kinds."""

    def test_the_pane_lists_only_vehicles( self ):
        profile = Profile( assets = [
            _vehicle( 'vehicle-1', 'Car', '30000' ),
            AssetProfile( handle = 'possession-1', name = 'Ring', asset_class = AssetClass.COLLECTIBLES,
                          opening_value = Decimal( '5000' ) ) ] )
        panes = VehiclesForm( profile = profile ).vehicle_panes
        self.assertEqual( len( panes ), 1 )
        listed = [ ( item[ 'handle' ], item[ 'name' ] ) for item in panes[ 0 ][ 'properties' ] ]
        self.assertEqual( listed, [ ( 'vehicle-1', 'Car' ) ] )


if __name__ == '__main__':
    unittest.main()
