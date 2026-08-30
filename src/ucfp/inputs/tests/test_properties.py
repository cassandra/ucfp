"""The unified `PropertyForm` (one editor for rentals and second homes) and `delete_property`.

The `property_type` choice drives the materialized class: a rental writes a `REAL_ESTATE_RENTAL` holding
with a depreciation `PropertyProfile`; a second home writes a `REAL_ESTATE_SECOND_HOME` with none. Either
type may carry a mortgage. Flipping an existing rental to a second home drops its rental rent (second homes
have none). `delete_property` removes a property and its secured debts but leaves the Plans as drift.
"""
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, IncomeTaxClass, RealPropertyType
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import (
    AssetProfile, Debt, IncomeFlow, LoanTerms, PropertyProfile, Profile )
from ucfp.inputs.properties import PropertyForm, delete_property
from ucfp.inputs.plans.schemas import LoanRepayment, Plans


def _apply( profile, *, handle = None, **fields ) -> Profile:
    data = QueryDict( mutable = True )
    data.update( fields )
    form = PropertyForm( data, profile = profile, plans = Plans(), handle = handle )
    assert form.is_valid(), form.errors
    result, _plans = form.apply( profile, Plans() )
    return result


class DeletePropertyTests( SimpleTestCase ):

    def _profile( self ):
        asset = AssetProfile(
            handle = 'property-1', name = 'Rental', asset_class = AssetClass.REAL_ESTATE_RENTAL,
            opening_value = Decimal( '300000' ) )
        mortgage = Debt(
            handle = 'debt-1', name = 'Mortgage', kind = DebtKind.MORTGAGE,
            balance = Decimal( '200000' ), secured_asset = 'property-1' )
        return Profile( assets = [ asset ], debts = [ mortgage ] )

    def test_deleting_a_property_removes_its_holding_and_secured_debt( self ):
        profile, _ = delete_property( self._profile(), Plans(), 'property-1' )
        self.assertEqual( profile.assets, [] )
        self.assertEqual( profile.debts, [] )                        # the secured mortgage goes with it

    def test_deleting_a_property_leaves_its_debts_repayment_plan_as_drift( self ):
        plans = Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'debt-1', interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] )
        _, reconciled = delete_property( self._profile(), plans, 'property-1' )
        self.assertEqual( [ r.debt_handle for r in reconciled.loan_repayments ], [ 'debt-1' ] )


class PropertyTypeTests( SimpleTestCase ):
    """The type choice materializes the right class -- a rental with its depreciation profile, a second
    home without -- and a type flip reconciles the parts that no longer apply."""

    def test_a_rental_materializes_a_rental_holding_with_a_depreciation_profile( self ):
        result = _apply(
            Profile(), handle = 'property-1', property_type = 'RENTAL_COMMERCIAL', name = 'Shopfront',
            value = '300,000', purchase_price = '250,000', building_basis = '200,000',
            acquisition_date = '2010-05' )
        asset = result.assets[ 0 ]
        self.assertEqual( asset.asset_class, AssetClass.REAL_ESTATE_RENTAL )
        self.assertEqual( asset.property.property_type, RealPropertyType.COMMERCIAL )
        self.assertEqual( asset.property.depreciable_basis, Decimal( '200000' ) )
        self.assertEqual( asset.property.acquisition_date, date( 2010, 5, 15 ) )

    def test_a_second_home_materializes_a_second_home_holding_with_no_profile( self ):
        result = _apply(
            Profile(), handle = 'property-1', property_type = 'SECOND_HOME', name = 'Cabin',
            value = '200,000', purchase_price = '150,000' )
        asset = result.assets[ 0 ]
        self.assertEqual( asset.asset_class, AssetClass.REAL_ESTATE_SECOND_HOME )
        self.assertIsNone( asset.property )

    def test_flipping_a_rental_to_a_second_home_drops_its_rental_rent( self ):
        # A second home has no rent, so the rental income flow keyed to this property is reconciled away.
        profile = Profile(
            assets = [ AssetProfile( handle = 'property-1', name = 'Duplex',
                                     asset_class = AssetClass.REAL_ESTATE_RENTAL,
                                     opening_value = Decimal( '300000' ),
                                     property = PropertyProfile(
                                         acquisition_date = date( 2010, 5, 1 ),
                                         depreciable_basis = Decimal( '200000' ),
                                         property_type = RealPropertyType.RESIDENTIAL ) ) ],
            income_flows = [ IncomeFlow(
                handle = 'income-1', name = 'Duplex Rent', subject_handle = None,
                income_tax_class = IncomeTaxClass.GROSS_RENTAL, amount = Decimal( '2000' ),
                property_handle = 'property-1' ) ] )
        result = _apply(
            profile, handle = 'property-1', property_type = 'SECOND_HOME', name = 'Duplex',
            value = '300,000', purchase_price = '250,000' )
        self.assertEqual( result.assets[ 0 ].asset_class, AssetClass.REAL_ESTATE_SECOND_HOME )
        self.assertEqual( result.income_flows, [] )                  # the rental rent dropped


class PropertyMortgageTermsTests( SimpleTestCase ):
    """The property mortgage carries the shared loan-terms fields: entered terms land on the mortgage
    `Debt`, and reopen an edit on them."""

    def _with_mortgage( self, **fields ) -> Profile:
        return _apply(
            Profile(), handle = 'property-1', property_type = 'SECOND_HOME', name = 'Cabin',
            value = '200,000', purchase_price = '150,000', **fields )

    def test_entered_terms_are_stored_on_the_mortgage( self ):
        profile  = self._with_mortgage(
            mortgage_balance = '120,000', loan_payment = '900', loan_term = '180' )
        mortgage = next( d for d in profile.debts if d.handle == 'property-1-mortgage' )
        self.assertEqual( mortgage.terms.remaining_term.months(), 180 )
        self.assertGreater( mortgage.terms.interest_rate.fraction, Decimal( '0' ) )   # back-solved

    def test_a_mortgage_without_terms_stores_none( self ):
        profile  = self._with_mortgage( mortgage_balance = '120,000' )
        mortgage = next( d for d in profile.debts if d.handle == 'property-1-mortgage' )
        self.assertIsNone( mortgage.terms )

    def test_stored_facts_pre_fill_on_edit( self ):
        profile = Profile(
            assets = [ AssetProfile( handle = 'property-1', name = 'Cabin',
                                     asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
                                     opening_value = Decimal( '200000' ),
                                     cost_basis = Decimal( '150000' ) ) ],
            debts = [ Debt( handle = 'property-1-mortgage', name = 'Cabin Mortgage',
                            kind = DebtKind.MORTGAGE, balance = Decimal( '120000' ),
                            secured_asset = 'property-1',
                            terms = LoanTerms( interest_rate = Rate.percent( 5 ),
                                               remaining_term = Duration( 180, TimeUnit.MONTH ),
                                               monthly_payment = Decimal( '900' ) ) ) ] )
        form = PropertyForm( profile = profile, plans = Plans(), handle = 'property-1' )
        self.assertEqual( form.initial[ 'property_type' ], 'SECOND_HOME' )
        self.assertEqual( form.initial[ 'loan_term' ], 180 )
        self.assertEqual( form.initial[ 'loan_payment' ], Decimal( '900' ) )
