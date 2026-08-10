"""PropertyExpensesForm durables (#129): the Default amount is authoritative, the calculator a helper.

Mirrors the recurring-expenses change for the property table: a durable property expense's Default is a
directly-typed amount, read as-is on save (never recomputed from its count/cost/lifespan calculator), with
those inputs only remembered to repopulate the panel.
"""
from dataclasses import replace
from decimal import Decimal

from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.inputs.property_expenses import PropertyExpensesForm


def _baseline_data( form ) -> QueryDict:
    """A POST mirroring an unbound form's own initial values, so a test overrides only the cells it means
    to and submits an otherwise-unchanged matrix."""
    data = QueryDict( mutable = True )
    for name in form.fields:
        value = form[ name ].value()
        data[ name ] = '' if value is None else str( value )
    return data


def _property_profile() -> Profile:
    """A one-property household -- enough for property expenses to apply (its matrix collapses to the
    single Default column)."""
    return Profile( assets = [ AssetProfile(
        handle = 'property-1', name = 'Home', asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
        opening_value = Decimal( '500000' ) ) ] )


def _two_property_profile() -> Profile:
    """Two rentals -- the matrix does NOT collapse, so a row shows its Default column plus per-property
    override cells (needed to exercise the durable default + override read path)."""
    return Profile( assets = [
        AssetProfile( handle = 'property-1', name = 'Rental A', asset_class = AssetClass.REAL_ESTATE_RENTAL,
                      opening_value = Decimal( '300000' ) ),
        AssetProfile( handle = 'property-2', name = 'Rental B', asset_class = AssetClass.REAL_ESTATE_RENTAL,
                      opening_value = Decimal( '250000' ) ) ] )


class PropertyDurableAmountAuthoritativeTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    @staticmethod
    def _durable_row( form ) -> int:
        return next( ri for ri, expense in enumerate( form._rows ) if expense.count is not None )

    def test_the_entered_default_wins_over_what_the_calculator_would_compute( self ):
        profile, plans = _property_profile(), Plans()
        form   = PropertyExpensesForm( profile = profile, plans = plans )
        ri     = self._durable_row( form )
        handle = form._rows[ ri ].handle
        data   = _baseline_data( form )
        data[ f'default_{ri}' ] = '150'                               # the typed Default...
        data[ f'count_{ri}' ], data[ f'cost_{ri}' ], data[ f'lifespan_{ri}' ] = '2', '400', '4'  # would be 200
        bound = PropertyExpensesForm( data, profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        durable = next( e for e in new_plans.property_expenses if e.handle == handle )
        self.assertEqual( durable.default_amount, Decimal( '150' ) )  # authoritative, not the calc's 200
        self.assertEqual(                                            # ...inputs still remembered
            ( durable.count, durable.cost_each, durable.lifespan ), ( 2, Decimal( '400' ), 4 ) )

    def test_a_blank_durable_default_saves_as_none( self ):
        profile, plans = _property_profile(), Plans()
        form   = PropertyExpensesForm( profile = profile, plans = plans )
        ri     = self._durable_row( form )
        handle = form._rows[ ri ].handle
        data   = _baseline_data( form )
        data[ f'default_{ri}' ] = ''                                  # cleared -- charges nothing
        bound = PropertyExpensesForm( data, profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        durable = next( e for e in new_plans.property_expenses if e.handle == handle )
        self.assertIsNone( durable.default_amount )                   # Optional Default: blank -> None

    def test_the_default_survives_a_no_edit_round_trip_without_recompute( self ):
        # Default hand-set to diverge from what the inputs would compute (2 x 400 / 4 = 200); a resubmit
        # with no edits keeps it, never recomputing from the remembered inputs.
        profile = _two_property_profile()                            # non-collapsed: Default is its own cell
        seed    = PropertyExpensesForm( profile = profile, plans = Plans() )
        stored  = replace( seed._rows[ self._durable_row( seed ) ],
                           default_amount = Decimal( '130' ),
                           count = 2, cost_each = Decimal( '400' ), lifespan = 4 )
        plans = Plans( property_expenses = [ stored ] )
        form  = PropertyExpensesForm( profile = profile, plans = plans )
        bound = PropertyExpensesForm( _baseline_data( form ), profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        durable = next( e for e in new_plans.property_expenses if e.handle == stored.handle )
        self.assertEqual( durable.default_amount, Decimal( '130' ) )   # not recomputed to 200
        self.assertEqual(
            ( durable.count, durable.cost_each, durable.lifespan ), ( 2, Decimal( '400' ), 4 ) )

    def test_a_durable_default_and_a_per_property_override_are_both_read( self ):
        profile, plans = _two_property_profile(), Plans()
        form   = PropertyExpensesForm( profile = profile, plans = plans )
        self.assertFalse( form._collapsed )                          # two properties -> a real matrix
        ri     = self._durable_row( form )
        handle = form._rows[ ri ].handle
        hi     = next( h for h in range( len( form._handles ) )      # a property this durable overrides
                       if f'override_{ri}_{h}' in form.fields )
        data   = _baseline_data( form )
        data[ f'default_{ri}' ]      = '120'
        data[ f'override_{ri}_{hi}' ] = '90'
        data[ f'count_{ri}' ], data[ f'cost_{ri}' ], data[ f'lifespan_{ri}' ] = '2', '400', '4'
        bound = PropertyExpensesForm( data, profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        durable = next( e for e in new_plans.property_expenses if e.handle == handle )
        self.assertEqual( durable.default_amount, Decimal( '120' ) )                    # Default from its cell
        self.assertEqual( durable.overrides[ form._handles[ hi ] ], Decimal( '90' ) )   # override from its cell
        self.assertEqual(                                                             # inputs still remembered
            ( durable.count, durable.cost_each, durable.lifespan ), ( 2, Decimal( '400' ), 4 ) )
