"""`delete_property` removes a property and its secured debts from the Profile, but leaves the Plans
untouched -- a repayment plan still keyed to the removed mortgage is *drift*, reconciled on demand at the
run surface rather than eagerly reaped here (the retired reap pattern this bugfix removed)."""
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from django.http import QueryDict

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, LoanTerms, Profile
from ucfp.inputs.properties import SecondHomeForm, delete_property
from ucfp.inputs.plans.schemas import LoanRepayment, Plans


class DeletePropertyTests( SimpleTestCase ):

    def _profile( self ):
        """A property holding with a mortgage secured against it."""
        asset = AssetProfile(
            handle = 'property-1', name = 'Rental', asset_class = AssetClass.REAL_ESTATE_RENTAL,
            opening_value = Decimal( '300000' ) )
        mortgage = Debt(
            handle = 'debt-1', name = 'Mortgage', kind = DebtKind.MORTGAGE,
            balance = Decimal( '200000' ), secured_asset = 'property-1' )
        return Profile( assets = [ asset ], debts = [ mortgage ] )

    def _plans_repaying( self, debt_handle ):
        return Plans( loan_repayments = [ LoanRepayment(
            debt_handle = debt_handle, interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] )

    def test_deleting_a_property_removes_its_holding_and_secured_debt( self ):
        profile, _ = delete_property( self._profile(), Plans(), 'property-1' )
        self.assertEqual( profile.assets, [] )
        self.assertEqual( profile.debts, [] )                        # the secured mortgage goes with it

    def test_deleting_a_property_leaves_its_debts_repayment_plan_as_drift( self ):
        # The retired reap: the repayment for the now-gone mortgage is kept, not stripped -- it surfaces
        # as drift at the run surface (a one-click reconcile), never silently reaped on delete.
        plans      = self._plans_repaying( 'debt-1' )
        _, reconciled = delete_property( self._profile(), plans, 'property-1' )
        self.assertEqual( [ r.debt_handle for r in reconciled.loan_repayments ], [ 'debt-1' ] )


class PropertyMortgageTermsTests( SimpleTestCase ):
    """The property mortgage carries the shared loan-terms fields (via the shared `_PropertyForm`
    skeleton): entered terms land on the mortgage `Debt`, and reopen an edit on them."""

    def _apply( self, **fields ):
        data = QueryDict( mutable = True )
        data.update( fields )
        form = SecondHomeForm( data, profile = Profile(), plans = Plans(), handle = 'second-home-1' )
        assert form.is_valid(), form.errors
        profile, _plans = form.apply( Profile(), Plans() )
        return profile

    def test_entered_terms_are_stored_on_the_mortgage( self ):
        profile  = self._apply( name = 'Cabin', value = '200,000', purchase_price = '150,000',
                                mortgage_balance = '120,000', loan_payment = '900', loan_term = '180' )
        mortgage = next( d for d in profile.debts if d.handle == 'second-home-1-mortgage' )
        self.assertEqual( mortgage.terms.remaining_term.months(), 180 )
        self.assertGreater( mortgage.terms.interest_rate.fraction, Decimal( '0' ) )   # back-solved

    def test_a_mortgage_without_terms_stores_none( self ):
        profile  = self._apply( name = 'Cabin', value = '200,000', purchase_price = '150,000',
                                mortgage_balance = '120,000' )
        mortgage = next( d for d in profile.debts if d.handle == 'second-home-1-mortgage' )
        self.assertIsNone( mortgage.terms )

    def test_stored_terms_pre_fill_on_edit( self ):
        profile = Profile(
            assets = [ AssetProfile( handle = 'second-home-1', name = 'Cabin',
                                     asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
                                     opening_value = Decimal( '200000' ),
                                     cost_basis = Decimal( '150000' ) ) ],
            debts = [ Debt( handle = 'second-home-1-mortgage', name = 'Cabin Mortgage',
                            kind = DebtKind.MORTGAGE, balance = Decimal( '120000' ),
                            secured_asset = 'second-home-1',
                            terms = LoanTerms( interest_rate = Rate.percent( 5 ),
                                               remaining_term = Duration( 180, TimeUnit.MONTH ),
                                               monthly_payment = Decimal( '900' ) ) ) ] )
        form = SecondHomeForm( profile = profile, plans = Plans(), handle = 'second-home-1' )
        self.assertEqual( form.initial[ 'loan_term' ], 180 )
        self.assertEqual( form.initial[ 'loan_payment' ], Decimal( '900' ) )
