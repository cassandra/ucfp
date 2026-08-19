"""Home Expenses per-column subtotals and totals (#182 Phase 3).

The property matrix shows, for each column (the shared Default, then each property), a subtotal per
category and an overall page total -- every row annualized and summed down the column. The column value
resolves the Default fallback: a property cell left blank inherits the Default, so its column total must
count the Default, not zero. These pin that resolution, the collapsed one-column case, and rendering.
"""
from dataclasses import replace
from decimal import Decimal

from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.inputs.property_expenses import PropertyExpensesForm
from ucfp.inputs.views import PropertyExpensesView

_MONTHLY = Duration( 1, TimeUnit.MONTH )


def _one_property_profile() -> Profile:
    """One owned residence -- the matrix collapses to a single value column."""
    return Profile( assets = [ AssetProfile(
        handle = 'property-1', name = 'Home', asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
        opening_value = Decimal( '500000' ) ) ] )


def _two_property_profile() -> Profile:
    """Two second homes (same, owner-paid context) -- a real matrix (Default plus a column per property)
    whose rows keep their catalog defaults, so the Default-fallback math these tests pin is not perturbed
    by the rental tenant-paid $0 seeding (#186)."""
    return Profile( assets = [
        AssetProfile( handle = 'property-1', name = 'Cabin', asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
                      opening_value = Decimal( '300000' ) ),
        AssetProfile( handle = 'property-2', name = 'Lake House', asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
                      opening_value = Decimal( '250000' ) ) ] )


def _uniform_plans( profile, default : Decimal, overrides = None ) -> Plans:
    """Plans whose every property expense carries `default`/month and the given `{handle: amount}`
    overrides, so the column totals are fully determined. Overrides not applicable to a row are pruned
    on merge, as usual."""
    seed = PropertyExpensesForm( profile = profile, plans = Plans() )
    rows = [ replace( expense, default_amount = default, interval = _MONTHLY,
                      overrides = dict( overrides or {} ) )
             for expense in seed._all ]
    return Plans( property_expenses = rows )


class PropertyExpenseTotalsTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    def test_collapsed_total_is_every_row_annualized( self ):
        form = PropertyExpensesForm(
            profile = _one_property_profile(), plans = _uniform_plans( _one_property_profile(), Decimal( '100' ) ) )
        self.assertTrue( form._collapsed )
        self.assertEqual( form.totals_row[ 0 ].amount, Decimal( '100' ) * 12 * len( form._rows ) )

    def test_collapsed_total_uses_a_stored_override_as_the_effective_value( self ):
        # The lone property's effective amount is its override when set, not the (ignored) Default.
        plans = _uniform_plans( _one_property_profile(), Decimal( '100' ),
                                overrides = { 'property-1': Decimal( '40' ) } )
        form  = PropertyExpensesForm( profile = _one_property_profile(), plans = plans )
        self.assertEqual( form.totals_row[ 0 ].amount, Decimal( '40' ) * 12 * len( form._rows ) )

    def test_a_row_not_applying_to_a_column_contributes_zero( self ):
        # A renting household with a second home: rent applies only to the rented-home column and the
        # ownership costs only to the second-home column, so each property column omits the rows N/A to
        # it and totals strictly less than the Default column, which counts every displayed row.
        profile = Profile(
            home_tenure = HousingTenure.RENT,
            assets = [ AssetProfile(
                handle = 'second-home-1', name = 'Cabin', asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
                opening_value = Decimal( '400000' ) ) ] )
        form = PropertyExpensesForm( profile = profile, plans = _uniform_plans( profile, Decimal( '100' ) ) )
        self.assertFalse( form._collapsed )
        default_total = form.totals_row[ 0 ].amount
        self.assertGreater( default_total, Decimal( '0' ) )
        for col in range( 1, len( form.columns ) ):
            self.assertLess( form.totals_row[ col ].amount, default_total )

    def test_property_column_totals_resolve_overrides_over_the_default( self ):
        profile = _two_property_profile()
        plans   = _uniform_plans( profile, Decimal( '100' ), overrides = { 'property-1': Decimal( '50' ) } )
        form    = PropertyExpensesForm( profile = profile, plans = plans )
        self.assertFalse( form._collapsed )
        rows          = len( form._rows )                       # every displayed row applies to both rentals
        default_total = Decimal( '100' ) * 12 * rows
        self.assertEqual( form.totals_row[ 0 ].amount, default_total )                  # Default column
        self.assertEqual( form.totals_row[ 1 ].amount, Decimal( '50' ) * 12 * rows )    # property-1: override wins
        self.assertEqual( form.totals_row[ 2 ].amount, default_total )                  # property-2: blank -> Default

    def test_page_total_equals_the_sum_of_the_category_subtotals( self ):
        profile = _two_property_profile()
        form    = PropertyExpensesForm(
            profile = profile, plans = _uniform_plans( profile, Decimal( '100' ) ) )
        for col in range( len( form.columns ) ):
            subtotal_sum = sum( ( section[ 'subtotals' ][ col ].amount for section in form.sections ),
                                Decimal( 0 ) )
            self.assertEqual( form.totals_row[ col ].amount, subtotal_sum )

    def test_the_total_and_subtotals_render_under_the_push_target_ids( self ):
        profile = _two_property_profile()
        form    = PropertyExpensesForm(
            profile = profile, plans = _uniform_plans( profile, Decimal( '100' ) ) )
        html = render_to_string(
            PropertyExpensesView.template, { 'property_form': form, 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertIn( 'Home Expenses Total', html )
        self.assertIn( 'id="home-total-0"', html )
        first_category = form.sections[ 0 ][ 'category' ].name.lower()
        self.assertIn( f'id="home-subtotal-{first_category}-0"', html )

    def test_totals_covers_every_subtotal_and_page_total( self ):
        profile    = _two_property_profile()
        form       = PropertyExpensesForm(
            profile = profile, plans = _uniform_plans( profile, Decimal( '100' ) ) )
        categories = { expense.category for expense in form._rows }
        self.assertEqual( len( form.totals ), len( form.columns ) * ( len( categories ) + 1 ) )
