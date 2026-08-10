"""RecurringExpensesForm durables (#129): the per-band amount is authoritative, the calculator a helper.

A durable expense (one carrying a `count`) used to have its amount computed from a count/cost/lifespan
calculator and forced age-flat. It is now a directly-typed per-band amount like any other expense: the
form reads the entered amounts as-is (never recomputing them from the calculator) and only *remembers* the
calculator inputs to repopulate the panel. These tests pin that authority and the per-band freedom.
"""
from decimal import Decimal

from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase

from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.recurring_expenses import RecurringExpensesForm


def _baseline_data( form ) -> QueryDict:
    """A POST mirroring an unbound form's own initial values -- every field at its rendered default -- so a
    test overrides only the cells it means to and submits an otherwise-unchanged table."""
    data = QueryDict( mutable = True )
    for name in form.fields:
        value = form[ name ].value()
        data[ name ] = '' if value is None else str( value )
    return data


class DurableAmountAuthoritativeTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )        # the durable catalog rows (count-carrying) are seeded

    @staticmethod
    def _durable_index( form ) -> int:
        return next( ei for ei, expense in enumerate( form._expenses ) if expense.count is not None )

    def test_the_entered_amount_wins_over_what_the_calculator_would_compute( self ):
        profile, plans = Profile(), Plans()
        form = RecurringExpensesForm( profile = profile, plans = plans )
        ei   = self._durable_index( form )
        data = _baseline_data( form )
        data[ f'amt_{ei}_0' ] = '100'                                  # the typed amount...
        data[ f'count_{ei}' ], data[ f'cost_{ei}' ], data[ f'lifespan_{ei}' ] = '3', '500', '5'  # would be 300
        bound = RecurringExpensesForm( data, profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        durable = new_plans.recurring_expenses[ ei ]
        self.assertEqual( durable.amounts, [ Decimal( '100' ) ] )      # authoritative, not the 300 the calc gives
        self.assertEqual(                                             # ...but the inputs are still remembered
            ( durable.count, durable.cost_each, durable.lifespan ), ( 3, Decimal( '500' ), 5 ) )

    def test_a_durable_may_vary_by_age_band( self ):
        profile, plans = Profile(), Plans( expense_spans = [ 65, None ] )
        form = RecurringExpensesForm( profile = profile, plans = plans )
        self.assertEqual( form.span_count, 2 )
        ei   = self._durable_index( form )
        data = _baseline_data( form )
        data[ f'amt_{ei}_0' ], data[ f'amt_{ei}_1' ] = '100', '250'    # a step up at 65
        bound = RecurringExpensesForm( data, profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        self.assertEqual(                                             # per-band, not flattened to one figure
            new_plans.recurring_expenses[ ei ].amounts, [ Decimal( '100' ), Decimal( '250' ) ] )

    def test_a_blank_durable_band_saves_as_zero( self ):
        profile, plans = Profile(), Plans()
        form = RecurringExpensesForm( profile = profile, plans = plans )
        ei   = self._durable_index( form )
        data = _baseline_data( form )
        data[ f'amt_{ei}_0' ] = ''                                     # cleared, like any other row
        bound = RecurringExpensesForm( data, profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        self.assertEqual( new_plans.recurring_expenses[ ei ].amounts, [ Decimal( '0' ) ] )
