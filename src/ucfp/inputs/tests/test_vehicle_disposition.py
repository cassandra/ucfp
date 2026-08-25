"""VehicleDispositionForm: a current vehicle's disposition round-trips, defaulting to Retain.

The value earning a test here is the per-vehicle disposition write (mirroring the Debt plan's per-debt
repayment): Retain is the default and stored as absence; Sell records a dated sale; Replace records a
dated sale plus a successor purchase carrying the current vehicle's name; editing pre-fills; and one
vehicle's edit leaves the others' dispositions intact. The list summary and the materialization are
covered elsewhere (this pins the input write).
"""
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.template.loader import render_to_string

from common.amortization import level_payment
from common.dataclass_json import from_json_data, to_json_data
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.debt_plan import DebtPlanForm
from ucfp.inputs.plans.enums import LeaseDispositionKind, PaymentMethod, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    LeasedVehicleDisposition, LoanRepayment, LoanTermsSnapshot, Plans, Vehicle, VehicleDisposition,
    VehiclePlan )
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, LeasedVehicle, LoanTerms, Profile
from ucfp.inputs.vehicle_disposition import (
    LeasedVehicleDispositionForm, VehicleDispositionForm,
    all_dispositions_context, dispositions_context, leased_dispositions_context )
from ucfp.inputs.vehicle_handles import loan_debt_handle


def _profile( *vehicles ) -> Profile:
    """A profile whose current vehicles are the given (handle, name) DEPRECIATING holdings."""
    return Profile( assets = [
        AssetProfile( handle = h, name = n, asset_class = AssetClass.DEPRECIATING,
                      opening_value = Decimal( '20000' ) )
        for h, n in vehicles ] )


def _financed_profile( handle = 'vehicle-1', name = 'Sedan', balance = '18000' ) -> Profile:
    """A profile with one owned, *financed* vehicle -- a DEPRECIATING holding plus the `AUTO` `Debt`
    secured against it (its `{v}-loan` handle), the current loan the disposition card's terms edit."""
    return Profile(
        assets = [ AssetProfile( handle = handle, name = name, asset_class = AssetClass.DEPRECIATING,
                                 opening_value = Decimal( '20000' ) ) ],
        debts  = [ Debt( handle = loan_debt_handle( handle ), name = f'{name} loan', kind = DebtKind.AUTO,
                         balance = Decimal( balance ), secured_asset = handle ) ] )


def _repayment( debt_handle = 'vehicle-1-loan', rate = '5', months = 36 ) -> LoanRepayment:
    return LoanRepayment( debt_handle = debt_handle, interest_rate = Rate.percent( Decimal( rate ) ),
                          remaining_term = Duration( months, TimeUnit.MONTH ) )


def _apply( profile, plans, handle, **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = VehicleDispositionForm( data, profile = profile, plans = plans, handle = handle )
    assert form.is_valid(), form.errors
    _profile, plans = form.apply( profile, plans )
    return plans


def _dispositions( plans ) -> list:
    return plans.vehicle_plan.dispositions if plans.vehicle_plan is not None else []


class VehicleDispositionFormTests( unittest.TestCase ):

    def test_a_fresh_vehicle_defaults_to_retain( self ):
        form = VehicleDispositionForm( profile = _profile( ( 'vehicle-1', 'Sedan' ) ),
                                       plans = Plans(), handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'kind' ], VehicleDispositionKind.KEEP.name )

    def test_a_sell_records_a_dated_sale( self ):
        plans = _apply( _profile( ( 'vehicle-1', 'Sedan' ) ), Plans(), 'vehicle-1',
                        kind = 'SELL', sale_date = '2032-06-01' )
        self.assertEqual( len( _dispositions( plans ) ), 1 )
        disposition = _dispositions( plans )[ 0 ]
        self.assertEqual( disposition.vehicle_handle, 'vehicle-1' )
        self.assertIs( disposition.kind, VehicleDispositionKind.SELL )
        self.assertEqual( ( disposition.sale_date.year, disposition.sale_date.month ), ( 2032, 6 ) )
        self.assertIsNone( disposition.replacement )              # no successor for a sell

    def test_a_replace_records_a_successor_carrying_the_current_name( self ):
        plans = _apply( _profile( ( 'vehicle-1', 'Old Sedan' ) ), Plans(), 'vehicle-1',
                        kind = 'REPLACE', sale_date = '2032-06-01', purchase_price = '40,000',
                        recurrence_years = '8', payment_method = 'CASH' )
        disposition = _dispositions( plans )[ 0 ]
        self.assertIs( disposition.kind, VehicleDispositionKind.REPLACE )
        self.assertIsNotNone( disposition.replacement )
        replacement = disposition.replacement
        self.assertEqual( replacement.name, 'Old Sedan' )         # the successor carries the current name
        self.assertEqual( replacement.purchase_price, Decimal( '40000' ) )
        self.assertEqual( replacement.recurrence_years, 8 )
        self.assertIs( replacement.payment_method, PaymentMethod.CASH )
        self.assertIsNone( replacement.purchase_date )            # supplied at materialization from `date`

    def test_retain_clears_any_stored_disposition( self ):
        existing = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL ) ] ) )
        plans = _apply( _profile( ( 'vehicle-1', 'Sedan' ) ), existing, 'vehicle-1', kind = 'KEEP' )
        self.assertEqual( _dispositions( plans ), [] )            # collapses back to the default (absence)

    def test_editing_one_vehicle_leaves_the_others_disposition_intact( self ):
        other    = VehicleDisposition( vehicle_handle = 'vehicle-2', kind = VehicleDispositionKind.SELL )
        existing = Plans( vehicle_plan = VehiclePlan( dispositions = [ other ] ) )
        profile  = _profile( ( 'vehicle-1', 'Sedan' ), ( 'vehicle-2', 'Truck' ) )
        plans    = _apply( profile, existing, 'vehicle-1', kind = 'SELL', sale_date = '2033-01-01' )
        handles  = { d.vehicle_handle for d in _dispositions( plans ) }
        self.assertEqual( handles, { 'vehicle-1', 'vehicle-2' } )

    def test_edit_pre_fills_from_a_stored_replacement( self ):
        car      = Vehicle( handle = '', name = 'Old Sedan', purchase_price = Decimal( '40000' ),
                            recurrence_years = 8, payment_method = PaymentMethod.LOAN,
                            down_payment = Decimal( '9000' ) )
        existing = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                                replacement = car ) ] ) )
        form = VehicleDispositionForm( profile = _profile( ( 'vehicle-1', 'Old Sedan' ) ),
                                       plans = existing, handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'kind' ], VehicleDispositionKind.REPLACE.name )
        self.assertEqual( form.initial[ 'purchase_price' ], Decimal( '40000' ) )
        self.assertEqual( form.initial[ 'payment_method' ], PaymentMethod.LOAN.name )
        self.assertEqual( form.initial[ 'down_payment' ], Decimal( '9000' ) )


class VehicleLoanTermsTests( unittest.TestCase ):
    """The current-loan terms (rate + months left) the card re-homes from the Debt plan: shown only for a
    financed vehicle, written as its `LoanRepayment`, pre-filled on edit, and kept with the disposition."""

    def test_a_financed_vehicle_shows_the_loan_subsection( self ):
        form = VehicleDispositionForm( profile = _financed_profile(), plans = Plans(), handle = 'vehicle-1' )
        self.assertTrue( form.is_financed )

    def test_a_cash_vehicle_has_no_loan_subsection( self ):
        form = VehicleDispositionForm( profile = _profile( ( 'vehicle-1', 'Sedan' ) ),
                                       plans = Plans(), handle = 'vehicle-1' )
        self.assertFalse( form.is_financed )

    def test_setting_terms_writes_the_repayment( self ):
        plans = _apply( _financed_profile(), Plans(), 'vehicle-1',
                        kind = 'KEEP', loan_rate = '5', loan_months = '36' )
        self.assertEqual( len( plans.loan_repayments ), 1 )
        repayment = plans.loan_repayments[ 0 ]
        self.assertEqual( repayment.debt_handle, 'vehicle-1-loan' )
        self.assertEqual( repayment.interest_rate, Rate.percent( Decimal( '5' ) ) )
        self.assertEqual( repayment.remaining_term, Duration( 36, TimeUnit.MONTH ) )

    def test_incomplete_terms_write_no_repayment( self ):
        plans = _apply( _financed_profile(), Plans(), 'vehicle-1', kind = 'KEEP', loan_rate = '5' )
        self.assertEqual( plans.loan_repayments, [] )                     # no months -> no terms yet

    def test_a_non_financed_vehicle_never_writes_a_repayment( self ):
        plans = _apply( _profile( ( 'vehicle-1', 'Sedan' ) ), Plans(), 'vehicle-1',
                        kind = 'KEEP', loan_rate = '5', loan_months = '36' )
        self.assertEqual( plans.loan_repayments, [] )

    def test_edit_pre_fills_stored_terms( self ):
        existing = Plans( loan_repayments = [ _repayment( rate = '4.5', months = 24 ) ] )
        form     = VehicleDispositionForm( profile = _financed_profile(), plans = existing,
                                           handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'loan_rate' ], Decimal( '4.5' ) )
        self.assertEqual( form.initial[ 'loan_months' ], 24 )

    def test_edit_pre_fills_the_implied_monthly( self ):
        existing = Plans( loan_repayments = [ _repayment( rate = '5', months = 36 ) ] )
        form     = VehicleDispositionForm( profile = _financed_profile( balance = '18000' ),
                                           plans = existing, handle = 'vehicle-1' )
        expected = round( level_payment( Decimal( '18000' ), Decimal( '0.05' ) / 12, 36 ) )
        self.assertEqual( form.initial[ 'loan_monthly' ], expected )   # the monthly the terms imply

    def test_edit_seeds_the_current_loan_from_profile_facts( self ):
        # No repayment yet: the current-loan fields seed from the auto Debt's contract terms (copy 1).
        profile = replace( _financed_profile( balance = '18000' ), debts = [ Debt(
            handle = 'vehicle-1-loan', name = 'Sedan loan', kind = DebtKind.AUTO,
            balance = Decimal( '18000' ), secured_asset = 'vehicle-1',
            terms = LoanTerms( interest_rate = Rate.percent( 5 ),
                               remaining_term = Duration( 36, TimeUnit.MONTH ),
                               monthly_payment = Decimal( '540' ) ) ) ] )
        form = VehicleDispositionForm( profile = profile, plans = Plans(), handle = 'vehicle-1' )
        self.assertEqual( form.initial[ 'loan_rate' ], Decimal( '5' ) )
        self.assertEqual( form.initial[ 'loan_months' ], 36 )

    def test_no_terms_and_no_repayment_leaves_the_rate_blank( self ):
        # Nothing is invented: without a repayment or Profile terms, the rate field carries no default.
        form = VehicleDispositionForm( profile = _financed_profile(), plans = Plans(), handle = 'vehicle-1' )
        self.assertIsNone( form.initial.get( 'loan_rate' ) )

    def test_a_no_js_monthly_back_solves_the_rate( self ):
        # Without JS the rate field is blank; the monthly payment + balance + months determine the rate. A
        # payment amortizing 18,000 at 5%/yr over 36 mo back-solves to ~5%.
        monthly = round( level_payment( Decimal( '18000' ), Decimal( '0.05' ) / 12, 36 ) )
        plans   = _apply( _financed_profile( balance = '18000' ), Plans(), 'vehicle-1',
                          kind = 'KEEP', loan_monthly = str( monthly ), loan_months = '36' )
        self.assertEqual( len( plans.loan_repayments ), 1 )
        # A whole-dollar monthly cannot encode the exact rate, so the back-solve is asserted loosely (~0.5%).
        self.assertAlmostEqual( plans.loan_repayments[ 0 ].interest_rate.fraction, Decimal( '0.05' ),
                                places = 2 )

    def test_an_implausible_monthly_stores_no_rate( self ):
        # $500/mo on $9,000 over 48 months implies ~60% APR -- beyond a plausible auto loan, so the
        # monthly/term is treated as not fitting the balance and no terms are stored (the client blanks the
        # rate and shows a hint; the server declines the derived rate here).
        plans = _apply( _financed_profile( balance = '9000' ), Plans(), 'vehicle-1',
                        kind = 'KEEP', loan_monthly = '500', loan_months = '48' )
        self.assertEqual( plans.loan_repayments, [] )

    def test_a_monthly_that_cannot_retire_the_balance_stores_no_rate( self ):
        # 150 x 48 = 7,200 < 9,000 -- no rate ever pays it off, so nothing is stored (not a bogus 0%).
        plans = _apply( _financed_profile( balance = '9000' ), Plans(), 'vehicle-1',
                        kind = 'KEEP', loan_monthly = '150', loan_months = '48' )
        self.assertEqual( plans.loan_repayments, [] )

    def test_a_directly_entered_high_rate_is_trusted( self ):
        # The plausibility guard is only on the monthly-derived path; a rate the user types stands as given.
        plans = _apply( _financed_profile(), Plans(), 'vehicle-1',
                        kind = 'KEEP', loan_rate = '35', loan_months = '36' )
        self.assertEqual( plans.loan_repayments[ 0 ].interest_rate, Rate.percent( Decimal( '35' ) ) )

    def test_the_rate_field_wins_when_both_are_given( self ):
        # The client keeps the rate authoritative (filling it from an edited monthly), so a submitted rate
        # is stored as-is even alongside a monthly.
        plans = _apply( _financed_profile(), Plans(), 'vehicle-1',
                        kind = 'KEEP', loan_rate = '6', loan_monthly = '999', loan_months = '36' )
        self.assertEqual( plans.loan_repayments[ 0 ].interest_rate, Rate.percent( Decimal( '6' ) ) )

    def test_saving_the_current_loan_records_a_terms_snapshot( self ):
        # The auto pipeline records the contract snapshot (copy 3) when the repayment is saved.
        profile = replace( _financed_profile( balance = '18000' ), debts = [ Debt(
            handle = 'vehicle-1-loan', name = 'Sedan loan', kind = DebtKind.AUTO,
            balance = Decimal( '18000' ), secured_asset = 'vehicle-1',
            terms = LoanTerms( interest_rate = Rate.percent( 5 ), remaining_term = Duration( 36, TimeUnit.MONTH ),
                               monthly_payment = Decimal( '540' ) ) ) ] )
        plans = _apply( profile, Plans(), 'vehicle-1', kind = 'KEEP', loan_rate = '5', loan_months = '36' )
        self.assertEqual( len( plans.loan_terms_snapshots ), 1 )
        snap = plans.loan_terms_snapshots[ 0 ]
        self.assertEqual( ( snap.debt_handle, snap.interest_rate, snap.remaining_term ),
                          ( 'vehicle-1-loan', Rate.percent( 5 ), Duration( 36, TimeUnit.MONTH ) ) )

    def test_clearing_the_current_loan_drops_its_snapshot( self ):
        plans  = Plans( loan_repayments = [ _repayment() ],
                        loan_terms_snapshots = [ LoanTermsSnapshot( 'vehicle-1-loan', Rate.percent( 5 ),
                                                                    Duration( 36, TimeUnit.MONTH ) ) ] )
        result = _apply( _financed_profile(), plans, 'vehicle-1', kind = 'KEEP' )   # no rate/months entered
        self.assertEqual( result.loan_terms_snapshots, [] )

    def test_terms_persist_alongside_a_disposition( self ):
        plans = _apply( _financed_profile(), Plans(), 'vehicle-1', kind = 'SELL',
                        sale_date = '2032-06-01', loan_rate = '6', loan_months = '48' )
        self.assertEqual( len( _dispositions( plans ) ), 1 )             # the sale...
        self.assertEqual( len( plans.loan_repayments ), 1 )             # ...and the loan terms both saved

    def test_the_debt_plan_lists_auto_loans_read_only_not_editable( self ):
        profile = replace( _financed_profile(), debts = [
            Debt( handle = 'vehicle-1-loan', name = 'Car loan', kind = DebtKind.AUTO,
                  balance = Decimal( '18000' ), secured_asset = 'vehicle-1' ),
            Debt( handle = 'debt-1', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                  balance = Decimal( '300000' ), secured_asset = 'property-1' ) ] )
        # The auto loan carries a vehicle-plan repayment; the mortgage is editable here.
        plans = Plans( loan_repayments = [ _repayment( rate = '5', months = 36 ) ] )
        form  = DebtPlanForm( profile = profile, plans = plans )
        self.assertEqual( [ row[ 'name' ] for row in form.rows ], [ 'Mortgage' ] )   # editable rows
        autos = form.auto_rows
        self.assertEqual( [ row[ 'name' ] for row in autos ], [ 'Car loan' ] )       # read-only rows
        self.assertIn( '5%, 36 mo left', autos[ 0 ][ 'terms' ] )

    def test_an_auto_loan_without_a_repayment_points_at_the_vehicle_plan( self ):
        form = DebtPlanForm( profile = _financed_profile(), plans = Plans() )
        self.assertEqual( form.auto_rows[ 0 ][ 'terms' ], 'Terms set in the Vehicle plan' )

    def test_the_debt_plan_seeds_rate_and_term_from_profile_facts( self ):
        profile = Profile( debts = [ Debt(
            handle = 'debt-1', name = 'Student loan', kind = DebtKind.STUDENT, balance = Decimal( '15000' ),
            terms = LoanTerms( interest_rate = Rate.percent( 6 ),
                               remaining_term = Duration( 48, TimeUnit.MONTH ),
                               monthly_payment = Decimal( '450' ) ) ) ] )
        row = DebtPlanForm( profile = profile, plans = Plans() ).rows[ 0 ]
        self.assertEqual( row[ 'rate' ].value(), Decimal( '6' ) )       # seeded from the contract facts
        self.assertEqual( row[ 'term' ].value(), 48 )

    def test_a_saved_repayment_wins_over_the_profile_facts( self ):
        profile = Profile( debts = [ Debt(
            handle = 'debt-1', name = 'Student loan', kind = DebtKind.STUDENT, balance = Decimal( '15000' ),
            terms = LoanTerms( interest_rate = Rate.percent( 6 ),
                               remaining_term = Duration( 48, TimeUnit.MONTH ) ) ) ] )
        plans = Plans( loan_repayments = [ _repayment( debt_handle = 'debt-1', rate = '4', months = 60 ) ] )
        row   = DebtPlanForm( profile = profile, plans = plans ).rows[ 0 ]
        self.assertEqual( row[ 'rate' ].value(), Decimal( '4' ) )       # the plan copy is authoritative
        self.assertEqual( row[ 'term' ].value(), 60 )


class DispositionListTests( unittest.TestCase ):
    """The list shows every current vehicle -- Retain when none is stored, else the stored kind summarized
    with the year it happens."""

    def test_lists_current_vehicles_with_summaries( self ):
        profile  = _profile( ( 'vehicle-1', 'Sedan' ), ( 'vehicle-2', 'Truck' ) )
        plans    = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL,
                                sale_date = date( 2032, 6, 1 ) ) ] ) )
        rows = dispositions_context( profile, plans )
        self.assertEqual( [ r[ 'name' ] for r in rows ], [ 'Sedan', 'Truck' ] )
        self.assertEqual( rows[ 0 ][ 'summary' ], 'Sell in 2032' )
        self.assertEqual( rows[ 1 ][ 'summary' ], 'Retain' )      # no stored disposition -> the default

    def test_a_financed_vehicles_row_carries_its_loan_status( self ):
        profile = _financed_profile()
        self.assertEqual( dispositions_context( profile, Plans() )[ 0 ][ 'loan' ], 'Loan terms not set' )
        with_terms = dispositions_context( profile, Plans( loan_repayments = [ _repayment() ] ) )
        self.assertEqual( with_terms[ 0 ][ 'loan' ], 'Loan: 5%, 36 mo left' )

    def test_a_cash_vehicles_row_has_no_loan_line( self ):
        row = dispositions_context( _profile( ( 'vehicle-1', 'Sedan' ) ), Plans() )[ 0 ]
        self.assertIsNone( row[ 'loan' ] )

    def test_combines_owned_and_leased_with_ownership_and_edit_route( self ):
        # The one list carries both kinds -- owned then leased -- each tagged with the editor its Edit opens.
        profile = Profile(
            assets = [ AssetProfile( handle = 'vehicle-1', name = 'Sedan',
                                     asset_class = AssetClass.DEPRECIATING,
                                     opening_value = Decimal( '20000' ) ) ],
            leased_vehicles = [ LeasedVehicle( handle = 'vehicle-2', name = 'Truck' ) ] )
        rows = all_dispositions_context( profile, Plans() )
        self.assertEqual( [ ( r[ 'name' ], r[ 'ownership' ], r[ 'edit_route' ] ) for r in rows ],
                          [ ( 'Sedan', 'Owned', 'vehicle_disposition_edit' ),
                            ( 'Truck', 'Leased', 'leased_disposition_edit' ) ] )

    def test_flags_only_an_incomplete_disposition( self ):
        # A chosen plan still missing structural fields is flagged; a complete one and the default Retain
        # (no stored disposition) are not -- the same predicate materialization gates on.
        profile = _profile( ( 'vehicle-1', 'Sedan' ), ( 'vehicle-2', 'Truck' ), ( 'vehicle-3', 'Coupe' ) )
        plans   = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                                sale_date = date( 2032, 1, 1 ) ),                     # no replacement terms
            VehicleDisposition( vehicle_handle = 'vehicle-2', kind = VehicleDispositionKind.SELL,
                                sale_date = date( 2032, 1, 1 ) ) ] ) )                # complete
        flags = { r[ 'name' ] : r[ 'incomplete' ] for r in dispositions_context( profile, plans ) }
        self.assertEqual( flags, { 'Sedan' : True, 'Truck' : False, 'Coupe' : False } )

    def test_flags_an_unconfigured_or_incomplete_leased_vehicle( self ):
        # A leased vehicle contributes nothing without its current-lease terms, so an unconfigured one
        # (no disposition) is flagged too -- unlike an owned Retain-by-default, a valid zero-input state.
        profile = Profile( leased_vehicles = [
            LeasedVehicle( handle = 'vehicle-1', name = 'Unset' ),
            LeasedVehicle( handle = 'vehicle-2', name = 'Configured' ) ] )
        configured = LeasedVehicleDisposition(
            vehicle_handle = 'vehicle-2', monthly = Decimal( '400' ), lease_end = date( 2030, 1, 1 ),
            kind = LeaseDispositionKind.RETURN )                              # complete current lease
        plans = Plans( vehicle_plan = VehiclePlan( leased_dispositions = [ configured ] ) )
        flags = { r[ 'name' ] : r[ 'incomplete' ] for r in leased_dispositions_context( profile, plans ) }
        self.assertEqual( flags, { 'Unset' : True, 'Configured' : False } )

    def test_the_incomplete_flag_survives_the_combined_list( self ):
        # all_dispositions_context merges owned then leased -- the one list the view renders -- so each
        # row's incomplete flag must carry through the merge (an incomplete owned Replace and an
        # unconfigured leased vehicle both flag).
        profile = Profile(
            assets = [ AssetProfile( handle = 'vehicle-1', name = 'Sedan',
                                     asset_class = AssetClass.DEPRECIATING,
                                     opening_value = Decimal( '20000' ) ) ],
            leased_vehicles = [ LeasedVehicle( handle = 'vehicle-2', name = 'Lease' ) ] )
        plans = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                                sale_date = date( 2032, 1, 1 ) ) ] ) )          # no replacement terms
        flags = { r[ 'name' ] : r[ 'incomplete' ] for r in all_dispositions_context( profile, plans ) }
        self.assertEqual( flags, { 'Sedan' : True, 'Lease' : True } )


def _leased_profile( *vehicles ) -> Profile:
    return Profile( leased_vehicles = [ LeasedVehicle( handle = h, name = n ) for h, n in vehicles ] )


def _leased_apply( profile, plans, handle, **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = LeasedVehicleDispositionForm( data, profile = profile, plans = plans, handle = handle )
    assert form.is_valid(), form.errors
    _profile, plans = form.apply( profile, plans )
    return plans


def _leased_dispositions( plans ) -> list:
    return plans.vehicle_plan.leased_dispositions if plans.vehicle_plan is not None else []


class LeasedDispositionFormTests( unittest.TestCase ):

    def test_a_fresh_lease_defaults_to_return( self ):
        form = LeasedVehicleDispositionForm( profile = _leased_profile( ( 'lease-1', 'Sedan' ) ),
                                             plans = Plans(), handle = 'lease-1' )
        self.assertEqual( form.initial[ 'kind' ], LeaseDispositionKind.RETURN.name )

    def test_a_bare_return_stores_nothing( self ):
        # Return with no terms is the default -- stored as absence, so the plan stays empty.
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Sedan' ) ), Plans(), 'lease-1',
                               kind = 'RETURN' )
        self.assertEqual( _leased_dispositions( plans ), [] )

    def test_a_return_with_terms_records_the_current_lease( self ):
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Sedan' ) ), Plans(), 'lease-1',
                               kind = 'RETURN', monthly = '400', lease_end = '2029-01-01' )
        disposition = _leased_dispositions( plans )[ 0 ]
        self.assertIs( disposition.kind, LeaseDispositionKind.RETURN )
        self.assertEqual( disposition.monthly, Decimal( '400' ) )
        self.assertEqual( disposition.lease_end, date( 2029, 1, 1 ) )
        self.assertIsNone( disposition.successor )

    def test_a_buy_with_cash_records_a_cash_successor_carrying_the_lease_name( self ):
        # The kind fixes the successor's payment method -- no payment field is submitted.
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Leased Sedan' ) ), Plans(), 'lease-1',
                               kind = 'BUY_CASH', monthly = '400', lease_end = '2029-01-01',
                               purchase_price = '30,000', recurrence_years = '7' )
        disposition = _leased_dispositions( plans )[ 0 ]
        self.assertIs( disposition.kind, LeaseDispositionKind.BUY_CASH )
        self.assertEqual( disposition.successor.name, 'Leased Sedan' )
        self.assertEqual( disposition.successor.purchase_price, Decimal( '30000' ) )
        self.assertIs( disposition.successor.payment_method, PaymentMethod.CASH )
        self.assertIsNone( disposition.successor.purchase_date )     # supplied at materialization

    def test_a_renew_records_a_lease_successor( self ):
        # Renew implies the lease payment type -- its successor is a LEASE, from the kind, not a picker.
        plans = _leased_apply( _leased_profile( ( 'lease-1', 'Sedan' ) ), Plans(), 'lease-1',
                               kind = 'RENEW', monthly = '400', lease_end = '2029-01-01',
                               monthly_payment = '450', recurrence_years = '3' )
        successor = _leased_dispositions( plans )[ 0 ].successor
        self.assertIs( successor.payment_method, PaymentMethod.LEASE )
        self.assertEqual( successor.monthly_payment, Decimal( '450' ) )

    def test_edit_pre_fills_the_current_lease_and_kind( self ):
        existing = Plans( vehicle_plan = VehiclePlan( leased_dispositions = [
            LeasedVehicleDisposition(
                vehicle_handle = 'lease-1', monthly = Decimal( '350' ), lease_end = date( 2028, 6, 1 ),
                kind = LeaseDispositionKind.RENEW ) ] ) )
        form = LeasedVehicleDispositionForm( profile = _leased_profile( ( 'lease-1', 'Sedan' ) ),
                                             plans = existing, handle = 'lease-1' )
        self.assertEqual( form.initial[ 'kind' ], LeaseDispositionKind.RENEW.name )
        self.assertEqual( form.initial[ 'monthly' ], Decimal( '350' ) )
        self.assertEqual( form.initial[ 'lease_end' ], date( 2028, 6, 1 ) )

    def test_the_list_summarizes_each_leased_vehicle( self ):
        profile = _leased_profile( ( 'lease-1', 'Sedan' ), ( 'lease-2', 'Truck' ) )
        plans   = Plans( vehicle_plan = VehiclePlan( leased_dispositions = [
            LeasedVehicleDisposition( vehicle_handle = 'lease-1', kind = LeaseDispositionKind.BUY_CASH,
                                      lease_end = date( 2029, 1, 1 ) ) ] ) )
        rows = leased_dispositions_context( profile, plans )
        self.assertEqual( rows[ 0 ][ 'summary' ], 'Buy with cash in 2029' )
        self.assertEqual( rows[ 1 ][ 'summary' ], 'Return' )        # no stored disposition -> the default


class DispositionSerializationTests( unittest.TestCase ):
    """A disposition round-trips through the JSON codec with its date intact -- the regression for the
    field once named `date`, which shadowed the `date` type when annotations were resolved and left the
    stored value an un-parsed string (crashing anything that used it as a date)."""

    def test_a_dated_disposition_round_trips_as_a_date( self ):
        plans = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.SELL,
                                sale_date = date( 2032, 6, 1 ) ) ] ) )
        restored = from_json_data( Plans, to_json_data( plans ) )
        self.assertEqual( restored, plans )
        self.assertIsInstance( restored.vehicle_plan.dispositions[ 0 ].sale_date, date )

    def test_a_replace_disposition_with_a_successor_round_trips( self ):
        car   = Vehicle( handle = '', name = 'Sedan', purchase_price = Decimal( '40000' ),
                         recurrence_years = 8, payment_method = PaymentMethod.LOAN )
        plans = Plans( vehicle_plan = VehiclePlan( dispositions = [
            VehicleDisposition( vehicle_handle = 'vehicle-1', kind = VehicleDispositionKind.REPLACE,
                                sale_date = date( 2032, 6, 1 ), replacement = car ) ] ) )
        self.assertEqual( from_json_data( Plans, to_json_data( plans ) ), plans )


class DispositionFormRenderTests( unittest.TestCase ):
    """The editor template renders, wiring the kind switch (revealing the date and the replacement) and,
    nested within the replacement, the payment switch -- the one server-side contract a JS test can't cover
    (that both switches' case values reach the markup)."""

    def _render( self ):
        form = VehicleDispositionForm( profile = _profile( ( 'vehicle-1', 'Sedan' ) ),
                                       plans = Plans(), handle = 'vehicle-1' )
        html = render_to_string(
            'inputs/interview/sections/vehicle_disposition_form.html',
            { 'disposition_form': form, 'handle': 'vehicle-1', 'AppConst': AppConst } )
        return form, html

    def test_both_switches_case_values_render( self ):
        form, html = self._render()
        attr = f'data-{AppConst.SWITCH_CASE_DATA_ATTR}'
        self.assertIn( f'{attr}="{form.dated_kinds}"', html )               # kind switch: the date
        self.assertIn( f'{attr}="{form.replace_kind}"', html )             # kind switch: the replacement
        self.assertIn( f'{attr}="{form.payment_field_methods}"', html )    # nested payment switch

    def test_the_current_loan_subsection_shows_only_when_financed( self ):
        financed = render_to_string(
            'inputs/interview/sections/vehicle_disposition_form.html',
            { 'disposition_form': VehicleDispositionForm( profile = _financed_profile(), plans = Plans(),
                                                          handle = 'vehicle-1' ),
              'handle': 'vehicle-1', 'AppConst': AppConst } )
        self.assertIn( 'Current loan', financed )
        self.assertNotIn( 'Current loan', self._render()[ 1 ] )             # a cash vehicle: no loan block

    def test_the_current_loan_block_carries_the_balance_and_calculator_hooks( self ):
        html = render_to_string(
            'inputs/interview/sections/vehicle_disposition_form.html',
            { 'disposition_form': VehicleDispositionForm( profile = _financed_profile( balance = '18000' ),
                                                          plans = Plans(), handle = 'vehicle-1' ),
              'handle': 'vehicle-1', 'AppConst': AppConst } )
        self.assertIn( AppConst.LOAN_CLASS, html )                                    # calculator wrapper
        self.assertIn( f'data-{AppConst.LOAN_BALANCE_DATA_ATTR}="18000"', html )      # balance on it
        self.assertIn( AppConst.LOAN_PAYMENT_CLASS, html )                            # the monthly input
        self.assertIn( '$18000', html )                                              # balance shown read-only


class LeasedDispositionFormRenderTests( unittest.TestCase ):
    """The leased editor renders its three bordered subsections (matching the owned card) and the
    kind-switch case values -- the server-side contract a JS test can't cover."""

    def test_the_subsections_and_switch_cases_render( self ):
        form = LeasedVehicleDispositionForm( profile = _leased_profile( ( 'vehicle-1', 'Sedan' ) ),
                                             plans = Plans(), handle = 'vehicle-1' )
        html = render_to_string(
            'inputs/interview/sections/leased_disposition_form.html',
            { 'leased_form': form, 'handle': 'vehicle-1', 'AppConst': AppConst } )
        for legend in ( 'Current lease', 'At lease end', 'Successor' ):
            self.assertIn( legend, html )
        attr = f'data-{AppConst.SWITCH_CASE_DATA_ATTR}'
        self.assertIn( f'{attr}="{form.successor_kinds}"', html )       # successor block: Renew/Buy
        self.assertIn( f'{attr}="{form.financed_kinds}"', html )        # the down/monthly row


class CompletenessPredicateTests( unittest.TestCase ):
    """The structural-completeness predicates that gate atomic materialization and drive the 'Needs
    details' badge -- one source of truth for 'this plan is fully entered'. Amounts stay optional; a lease
    needs no purchase price (it is priced by its payments, so its readiness rests on the interval alone)."""

    def test_cash_vehicle_needs_a_price_and_interval_then_a_date( self ):
        bare = Vehicle( handle = 'v', payment_method = PaymentMethod.CASH )
        self.assertFalse( bare.has_structural_terms )
        priced = replace( bare, purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        self.assertTrue( priced.has_structural_terms )
        self.assertFalse( priced.is_materializable )                       # structural, but no purchase date
        self.assertTrue( replace( priced, purchase_date = date( 2030, 1, 1 ) ).is_materializable )

    def test_lease_vehicle_needs_its_interval_and_monthly_not_a_price( self ):
        bare = Vehicle( handle = 'v', payment_method = PaymentMethod.LEASE, recurrence_years = 3 )
        self.assertFalse( bare.has_structural_terms )                      # a lease needs its monthly cost
        priced = replace( bare, monthly_payment = Decimal( '400' ) )
        self.assertTrue( priced.has_structural_terms )                     # interval + monthly, and no price
        self.assertTrue( replace( priced, purchase_date = date( 2030, 1, 1 ) ).is_materializable )

    def test_owned_disposition_completeness_by_kind( self ):
        keep = VehicleDisposition( vehicle_handle = 'v', kind = VehicleDispositionKind.KEEP )
        self.assertTrue( keep.is_complete )                               # Retain needs nothing
        sell = VehicleDisposition( vehicle_handle = 'v', kind = VehicleDispositionKind.SELL )
        self.assertFalse( sell.is_complete )
        self.assertTrue( replace( sell, sale_date = date( 2030, 1, 1 ) ).is_complete )
        replacement = Vehicle( handle = '', purchase_price = Decimal( '30000' ), recurrence_years = 5 )
        dated = VehicleDisposition( vehicle_handle = 'v', kind = VehicleDispositionKind.REPLACE,
                                    sale_date = date( 2030, 1, 1 ) )
        self.assertFalse( dated.is_complete )                            # dated, but no replacement terms
        self.assertTrue( replace( dated, replacement = replacement ).is_complete )

    def test_leased_disposition_completeness_by_kind( self ):
        ret = LeasedVehicleDisposition( vehicle_handle = 'v', kind = LeaseDispositionKind.RETURN )
        self.assertFalse( ret.is_complete )                              # needs a lease-end and a monthly
        dated = replace( ret, lease_end = date( 2030, 1, 1 ) )
        self.assertFalse( dated.is_complete )                            # still missing the current monthly
        current = replace( dated, monthly = Decimal( '300' ) )
        self.assertTrue( current.is_complete )                           # Return: lease-end + current monthly
        successor = Vehicle( handle = '', payment_method = PaymentMethod.LEASE,
                             recurrence_years = 3, monthly_payment = Decimal( '450' ) )
        renew = replace( current, kind = LeaseDispositionKind.RENEW )
        self.assertFalse( renew.is_complete )                            # a renewed lease needs its terms
        self.assertTrue( replace( renew, successor = successor ).is_complete )


if __name__ == '__main__':
    unittest.main()
