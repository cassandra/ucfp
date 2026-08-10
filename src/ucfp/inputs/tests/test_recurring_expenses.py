"""RecurringExpensesForm durables (#129): the per-band amount is authoritative, the calculator a helper.

A durable expense (one carrying a `count`) used to have its amount computed from a count/cost/lifespan
calculator and forced age-flat. It is now a directly-typed per-band amount like any other expense: the
form reads the entered amounts as-is (never recomputing them from the calculator) and only *remembers* the
calculator inputs to repopulate the panel. These tests pin that authority and the per-band freedom.
"""
from dataclasses import replace
from decimal import Decimal

from django.core.management import call_command
from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.recurring_expenses import RecurringExpensesForm

_SECTION_TEMPLATE = 'inputs/interview/sections/recurring_expenses.html'


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

    def test_a_durable_row_renders_editable_with_the_auto_fill_helper( self ):
        form = RecurringExpensesForm( profile = Profile(), plans = Plans() )
        ei   = self._durable_index( form )
        attrs = form.fields[ f'amt_{ei}_0' ].widget.attrs
        self.assertNotIn( 'readonly', attrs )                          # directly editable (Phase 1)
        self.assertIn( AppConst.CALC_TARGET_CLASS, attrs[ 'class' ] )  # still a calculator fill target
        html = render_to_string(
            _SECTION_TEMPLATE, { 'recurring_form': form, 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        # The durable row's panel offers an Auto fill checkbox -- checked, bound to the row's calc id.
        self.assertInHTML(
            f'<input type="checkbox" class="{AppConst.CALC_AUTOFILL_CLASS}" '
            f'data-{AppConst.CALC_DATA_ATTR}="{ei}" '
            f'aria-label="Auto fill amounts from the calculator" checked>', html )

    def test_a_durable_survives_a_no_edit_round_trip_without_recompute( self ):
        # Amounts hand-set to diverge from what the remembered inputs would compute (3 x 500 / 5 = 300):
        # a plain resubmit with no edits must keep the amounts and the inputs, never recomputing from them.
        spans  = [ 65, None ]
        seed   = RecurringExpensesForm( profile = Profile(), plans = Plans( expense_spans = spans ) )
        stored = replace( seed._expenses[ self._durable_index( seed ) ],
                          amounts = [ Decimal( '100' ), Decimal( '400' ) ],
                          count = 3, cost_each = Decimal( '500' ), lifespan = 5 )
        plans  = Plans( expense_spans = spans, recurring_expenses = [ stored ] )
        form   = RecurringExpensesForm( profile = Profile(), plans = plans )
        bound  = RecurringExpensesForm( _baseline_data( form ), profile = Profile(), plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( Profile(), plans )
        durable = next( e for e in new_plans.recurring_expenses if e.handle == stored.handle )
        self.assertEqual( durable.amounts, [ Decimal( '100' ), Decimal( '400' ) ] )   # not recomputed to 300
        self.assertEqual(
            ( durable.count, durable.cost_each, durable.lifespan ), ( 3, Decimal( '500' ), 5 ) )

    def test_a_durable_with_no_calculator_inputs_keeps_its_amounts( self ):
        # Entered amounts but a blank calculator: the amounts stand on their own and the inputs read back
        # None (the "charge nothing" case the removed durable_amount() used to guard).
        profile, plans = Profile(), Plans()
        form = RecurringExpensesForm( profile = profile, plans = plans )
        ei   = self._durable_index( form )
        data = _baseline_data( form )
        data[ f'amt_{ei}_0' ] = '175'
        data[ f'count_{ei}' ] = data[ f'cost_{ei}' ] = data[ f'lifespan_{ei}' ] = ''
        bound = RecurringExpensesForm( data, profile = profile, plans = plans )
        self.assertTrue( bound.is_valid(), bound.errors )
        _profile, new_plans = bound.apply( profile, plans )
        durable = new_plans.recurring_expenses[ ei ]
        self.assertEqual( durable.amounts, [ Decimal( '175' ) ] )
        self.assertIsNone( durable.count )

    def test_a_durable_that_varies_by_band_flags_the_change_like_any_row( self ):
        # Phase 3: now that a durable can differ across bands, it earns the same up/down change flags as
        # every other row -- the scan-for-what-changes affordance no longer skips durables.
        spans    = [ 65, None ]
        seed     = RecurringExpensesForm( profile = Profile(), plans = Plans( expense_spans = spans ) )
        template = seed._expenses[ self._durable_index( seed ) ]      # a catalog durable's handle + count
        varying  = replace( template, amounts = [ Decimal( '100' ), Decimal( '250' ) ] )
        form  = RecurringExpensesForm(
            profile = Profile(), plans = Plans( expense_spans = spans, recurring_expenses = [ varying ] ) )
        ei    = next( i for i, e in enumerate( form._expenses ) if e.handle == template.handle )
        cells = form._row( ei, form._expenses[ ei ] )[ 'cells' ]
        self.assertFalse( cells[ 0 ][ 'changed' ] )                    # the first band is the baseline
        self.assertTrue( cells[ 1 ][ 'changed' ] )                     # 100 -> 250 is a change...
        self.assertEqual( cells[ 1 ][ 'direction' ], 'up' )           # ...a step up
