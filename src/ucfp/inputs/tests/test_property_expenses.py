"""PropertyExpensesForm durables (#129): the Default amount is authoritative, the calculator a helper.

Mirrors the recurring-expenses change for the property table: a durable property expense's Default is a
directly-typed amount, read as-is on save (never recomputed from its count/cost/lifespan calculator), with
those inputs only remembered to repopulate the panel.
"""
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
