"""The vehicle handle scheme (#151 Phase 1): the mint helpers and the `root_vehicle` inverse that resolves
any vehicle account handle -- holding, loan, interest, a derived replacement/successor, or the secured-loan
debt -- back to the one `vehicle-N` it belongs to (so a current vehicle and its replacements group as one).
"""
from django.test import SimpleTestCase

from ucfp.inputs.vehicle_handles import (
    loan_debt_handle, replacement_handle, root_vehicle, successor_handle, vehicle_holding_handle,
    vehicle_loan_handle, vehicle_loan_interest_handle )


class MintTests( SimpleTestCase ):

    def test_the_mint_helpers_produce_the_scheme( self ):
        self.assertEqual( vehicle_holding_handle( 'vehicle-3' ), 'vehicle:vehicle-3' )
        self.assertEqual( vehicle_loan_handle( 'vehicle-3' ), 'vehicle-loan:vehicle-3' )
        self.assertEqual( vehicle_loan_interest_handle( 'vehicle-3' ), 'vehicle-loan-interest:vehicle-3' )
        self.assertEqual( loan_debt_handle( 'vehicle-3' ), 'vehicle-3-loan' )
        self.assertEqual( replacement_handle( 'vehicle-3' ), 'vehicle-3-replacement' )
        self.assertEqual( successor_handle( 'vehicle-3' ), 'vehicle-3-successor' )


class RootVehicleTests( SimpleTestCase ):

    def test_it_resolves_every_account_and_derived_form_to_the_root( self ):
        for handle in ( 'vehicle-3',                                 # the vehicle handle itself
                        'vehicle:vehicle-3',                         # holding account
                        'vehicle-loan:vehicle-3',                    # current loan (cycle-less)
                        'vehicle-loan:vehicle-3:0',                  # recurring loan, first cycle
                        'vehicle-loan:vehicle-3:2',                  # recurring loan, later cycle
                        'vehicle-loan-interest:vehicle-3:0',         # interest account
                        'vehicle-3-loan' ):                          # the secured-loan debt fact
            self.assertEqual( root_vehicle( handle ), 'vehicle-3', handle )

    def test_a_replacement_and_its_loans_share_the_current_vehicles_root( self ):
        # The whole point: a Replace successor derives `vehicle-3-replacement`, so it and its loans resolve
        # to the same root as the current vehicle -- letting the run table group them as one.
        for handle in ( 'vehicle-3-replacement',
                        'vehicle:vehicle-3-replacement',
                        'vehicle-loan:vehicle-3-replacement:2',
                        'vehicle-loan-interest:vehicle-3-replacement:0',
                        'vehicle-3-successor' ):
            self.assertEqual( root_vehicle( handle ), 'vehicle-3', handle )

    def test_it_returns_none_outside_the_vehicle_scheme( self ):
        for handle in ( 'debt-1', 'cash', 'stocks', 'property-tax:rental-1', 'vehicle-loan:', '' ):
            self.assertIsNone( root_vehicle( handle ), handle )

    def test_the_mint_helpers_round_trip_through_root_vehicle( self ):
        for mint in ( vehicle_holding_handle, vehicle_loan_handle, vehicle_loan_interest_handle,
                      loan_debt_handle, replacement_handle, successor_handle ):
            # Replacement/successor resolve past their own derivation, so mint-then-root returns the root.
            self.assertEqual( root_vehicle( mint( 'vehicle-7' ) ), 'vehicle-7', mint.__name__ )
