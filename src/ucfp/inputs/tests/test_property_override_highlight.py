"""Home Expenses override highlight: a per-property cell that departs from the row's Default is flagged.

The counterpart of the recurring page's per-band change highlight -- here a filled override whose amount
differs from the shared Default is tinted, while a blank cell (which inherits the Default) and an
override equal to the Default are not. These pin the server-rendered initial state; the live toggling as
a value is typed is JavaScript (`flagPropertyOverrides`).
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
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.inputs.property_expenses import PropertyExpensesForm
from ucfp.inputs.views import PropertyExpensesView

_MONTHLY = Duration( 1, TimeUnit.MONTH )


def _two_property_profile() -> Profile:
    # Two second homes (owner-paid context) so a plain, override-free matrix carries no differences: the
    # rental tenant-paid $0 seeding (#186) would itself flag utility cells, which these differ-mechanic
    # tests are not about.
    return Profile( assets = [
        AssetProfile( handle = 'property-1', name = 'Cabin', asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
                      opening_value = Decimal( '300000' ) ),
        AssetProfile( handle = 'property-2', name = 'Lake House', asset_class = AssetClass.REAL_ESTATE_SECOND_HOME,
                      opening_value = Decimal( '250000' ) ) ] )


def _form( default, overrides = None ) -> PropertyExpensesForm:
    """A two-property matrix whose every row carries `default` and the given `{handle: amount}`
    overrides, so a chosen cell's differ-state is determined."""
    profile = _two_property_profile()
    seed    = PropertyExpensesForm( profile = profile, plans = Plans() )
    rows    = [ replace( expense, default_amount = default, interval = _MONTHLY,
                         overrides = dict( overrides or {} ) )
                for expense in seed._all ]
    return PropertyExpensesForm( profile = profile, plans = Plans( property_expenses = rows ) )


def _first_row_cells( form : PropertyExpensesForm ) -> list:
    return form.sections[ 0 ][ 'rows' ][ 0 ][ 'cells' ]    # [ Default, property-1, property-2 ]


class PropertyOverrideHighlightTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    def test_the_default_cell_is_never_flagged( self ):
        self.assertFalse( _first_row_cells( _form( Decimal( '100' ),
                                                   { 'property-1': Decimal( '50' ) } ) )[ 0 ][ 'differs' ] )

    def test_an_override_differing_from_the_default_is_flagged( self ):
        cells = _first_row_cells( _form( Decimal( '100' ), { 'property-1': Decimal( '50' ) } ) )
        self.assertTrue( cells[ 1 ][ 'differs' ] )         # property-1: 50 vs 100
        self.assertFalse( cells[ 2 ][ 'differs' ] )        # property-2: blank, inherits the Default

    def test_an_override_equal_to_the_default_is_not_flagged( self ):
        cells = _first_row_cells( _form( Decimal( '100' ), { 'property-1': Decimal( '100' ) } ) )
        self.assertFalse( cells[ 1 ][ 'differs' ] )

    def test_a_zero_override_against_a_nonzero_default_is_flagged( self ):
        cells = _first_row_cells( _form( Decimal( '100' ), { 'property-1': Decimal( '0' ) } ) )
        self.assertTrue( cells[ 1 ][ 'differs' ] )         # $0 here vs $100 default is a real difference

    def test_a_zero_override_against_a_blank_default_is_not_flagged( self ):
        cells = _first_row_cells( _form( None, { 'property-1': Decimal( '0' ) } ) )
        self.assertFalse( cells[ 1 ][ 'differs' ] )        # blank Default reads as zero

    def test_a_flagged_cell_renders_the_highlight_class_and_tooltip( self ):
        html = render_to_string(
            PropertyExpensesView.template,
            { 'property_form': _form( Decimal( '100' ), { 'property-1': Decimal( '50' ) } ),
              'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertIn( AppConst.PROPERTY_DIFFERS_CLASS, html )
        self.assertIn( AppConst.PROPERTY_DIFFERS_TITLE, html )   # a non-colour cue for the tint

    def test_nothing_differs_renders_no_highlight_class( self ):
        html = render_to_string(
            PropertyExpensesView.template,
            { 'property_form': _form( Decimal( '100' ) ), 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertNotIn( AppConst.PROPERTY_DIFFERS_CLASS, html )
