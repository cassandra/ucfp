"""Current vehicle loans materialize vehicle-scoped (#151 Phase 2): a current owned vehicle's `Debt(AUTO)`
becomes an engine loan under `vehicle-loan:{v}` (liability) + `vehicle-loan-interest:{v}` (interest) --
composed with its Plans `LoanRepayment` -- and is excluded from the generic `_loans` (non-vehicle debts).
So a current car and its future replacements share one root, and its interest is groupable.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile
from ucfp.inputs.vehicle_handles import loan_debt_handle
from ucfp.planning.materialization import _current_vehicle_loans, _loans


def _vehicle_and_loan( balance = '20000' ):
    asset = AssetProfile( handle = 'vehicle-1', name = 'Civic', asset_class = AssetClass.DEPRECIATING,
                          opening_value = Decimal( '25000' ) )
    debt  = Debt( handle = loan_debt_handle( 'vehicle-1' ), name = 'Civic loan', kind = DebtKind.AUTO,
                  balance = Decimal( balance ), secured_asset = 'vehicle-1' )
    return asset, debt


def _repayment( debt_handle ):
    return LoanRepayment( debt_handle = debt_handle, interest_rate = Rate.percent( Decimal( '5' ) ),
                          remaining_term = Duration( 36, TimeUnit.MONTH ) )


class CurrentVehicleLoanTests( SimpleTestCase ):

    def test_an_auto_debt_with_terms_materializes_vehicle_scoped( self ):
        asset, debt = _vehicle_and_loan()
        profile     = Profile( assets = [ asset ], debts = [ debt ] )
        plans       = Plans( loan_repayments = [ _repayment( debt.handle ) ] )
        loan        = _current_vehicle_loans( profile, plans )[ 0 ]
        self.assertEqual( loan.handle, 'vehicle-loan:vehicle-1' )
        self.assertEqual( loan.interest_handle, 'vehicle-loan-interest:vehicle-1' )
        self.assertEqual( loan.opening_balance, Decimal( '20000' ) )
        self.assertEqual( loan.interest_rate, Rate.percent( Decimal( '5' ) ) )
        self.assertEqual( loan.term, Duration( 36, TimeUnit.MONTH ) )
        self.assertEqual( loan.interest_class, ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST )

    def test_the_generic_loans_exclude_the_auto_debt( self ):
        asset, debt = _vehicle_and_loan()
        profile     = Profile( assets = [ asset ], debts = [ debt ] )
        plans       = Plans( loan_repayments = [ _repayment( debt.handle ) ] )
        self.assertEqual( _loans( profile, plans ), [] )          # the auto loan is not a generic loan

    def test_an_auto_debt_without_terms_is_not_yet_a_loan( self ):
        asset, debt = _vehicle_and_loan()
        profile     = Profile( assets = [ asset ], debts = [ debt ] )
        self.assertEqual( _current_vehicle_loans( profile, Plans() ), [] )   # no repayment -> no loan

    def test_a_mortgage_still_goes_through_the_generic_loans( self ):
        mortgage = Debt( handle = 'debt-1', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                         balance = Decimal( '300000' ), secured_asset = 'property-1' )
        profile  = Profile( debts = [ mortgage ] )
        plans    = Plans( loan_repayments = [ _repayment( 'debt-1' ) ] )
        generic  = _loans( profile, plans )
        self.assertEqual( [ loan.handle for loan in generic ], [ 'debt-1' ] )   # own handle, not vehicle-scoped
        self.assertEqual( _current_vehicle_loans( profile, plans ), [] )
