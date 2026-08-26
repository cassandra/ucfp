"""HomeForm's tenure is unset until the household answers the housing question.

The residence radio starts with no selection (a fresh profile has home_tenure=None), so the switch
shows no fields until a choice is made -- soliciting an explicit answer. 'Neither' stays a distinct
explicit choice (no home), separate from the unselected start.
"""
import unittest
from decimal import Decimal

from django.http import QueryDict

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.inputs.interview import HomeForm
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.enums import DebtKind, HousingTenure
from ucfp.inputs.profile.schemas import (
    RESIDENCE_MORTGAGE_HANDLE, AssetProfile, Debt, LoanTerms, Profile )
from ucfp.accounts.enums import AssetClass


def _applied( **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = HomeForm( data, profile = Profile(), plans = Plans() )
    assert form.is_valid(), form.errors
    profile, _plans = form.apply( Profile(), Plans() )
    return profile


class HomeTenureTests( unittest.TestCase ):

    def test_fresh_profile_starts_with_no_tenure( self ):
        self.assertIsNone( Profile().home_tenure )

    def test_blank_tenure_is_valid_and_stays_unset( self ):
        self.assertIsNone( _applied().home_tenure )   # no radio chosen -- not required, holds no tenure

    def test_choosing_own_records_it( self ):
        self.assertIs( _applied( tenure = 'own', home_value = '500,000' ).home_tenure, HousingTenure.OWN )

    def test_neither_is_a_distinct_explicit_answer( self ):
        self.assertIs( _applied( tenure = 'neither' ).home_tenure, HousingTenure.NEITHER )


class MonthlyRentTests( unittest.TestCase ):
    """The current monthly rent is a Profile fact, captured only for the Rent tenure."""

    def test_rent_tenure_records_the_monthly_rent( self ):
        self.assertEqual(
            _applied( tenure = 'rent', monthly_rent = '1,800' ).home_monthly_rent, Decimal( '1800' ) )

    def test_rent_is_recorded_only_for_the_rent_tenure( self ):
        # A rent amount posted while owning is ignored -- the fact belongs to the Rent case.
        self.assertIsNone(
            _applied( tenure = 'own', home_value = '500,000', monthly_rent = '1,800' ).home_monthly_rent )

    def test_a_blank_rent_is_not_recorded( self ):
        self.assertIsNone( _applied( tenure = 'rent' ).home_monthly_rent )

    def test_a_stored_rent_prefills_the_field( self ):
        form = HomeForm( profile = Profile( home_tenure = HousingTenure.RENT,
                                            home_monthly_rent = Decimal( '1800' ) ), plans = Plans() )
        self.assertEqual( form[ 'monthly_rent' ].value(), Decimal( '1800' ) )

    def test_switching_away_from_rent_clears_the_fact( self ):
        data = QueryDict( mutable = True )
        data.update( tenure = 'own', home_value = '500,000' )
        form = HomeForm( data, profile = Profile( home_monthly_rent = Decimal( '1800' ) ), plans = Plans() )
        self.assertTrue( form.is_valid(), form.errors )
        profile, _plans = form.apply( Profile( home_monthly_rent = Decimal( '1800' ) ), Plans() )
        self.assertIsNone( profile.home_monthly_rent )


class ResidenceMortgageTermsTests( unittest.TestCase ):
    """The residence mortgage carries the shared loan-terms fields: entered terms are captured on the
    mortgage `Debt`, and reopen an edit on them."""

    def _mortgage( self, profile ) -> Debt:
        return next( d for d in profile.debts if d.handle == RESIDENCE_MORTGAGE_HANDLE )

    def test_entered_terms_are_stored_on_the_mortgage( self ):
        profile = _applied( tenure = 'own', home_value = '500,000', mortgage_balance = '300,000',
                            loan_payment = '1800', loan_term = '240' )
        terms   = self._mortgage( profile ).terms
        self.assertEqual( terms.remaining_term.months(), 240 )
        self.assertGreater( terms.interest_rate.fraction, Decimal( '0' ) )   # back-solved from the payment

    def test_a_mortgage_without_terms_stores_none( self ):
        profile = _applied( tenure = 'own', home_value = '500,000', mortgage_balance = '300,000' )
        self.assertIsNone( self._mortgage( profile ).terms )

    def test_stored_terms_pre_fill_on_edit( self ):
        profile = Profile(
            home_tenure = HousingTenure.OWN,
            assets = [ AssetProfile( handle = 'residence', name = 'Home',
                                     asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
                                     opening_value = Decimal( '500000' ) ) ],
            debts = [ Debt( handle = RESIDENCE_MORTGAGE_HANDLE, name = 'Mortgage',
                            kind = DebtKind.MORTGAGE, balance = Decimal( '300000' ),
                            secured_asset = 'residence',
                            terms = LoanTerms( interest_rate = Rate.percent( 4 ),
                                               remaining_term = Duration( 240, TimeUnit.MONTH ),
                                               monthly_payment = Decimal( '1800' ) ) ) ] )
        form = HomeForm( profile = profile, plans = Plans() )
        self.assertEqual( form.initial[ 'loan_rate' ], Decimal( '4' ) )
        self.assertEqual( form.initial[ 'loan_term' ], 240 )
        self.assertEqual( form.initial[ 'loan_payment' ], Decimal( '1800' ) )
