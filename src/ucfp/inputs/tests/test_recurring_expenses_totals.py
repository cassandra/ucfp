"""Living Expenses per-span subtotals and totals (#182 Phase 2).

The pane shows, for each age-span column, a subtotal per category and an overall page total -- every
row's amount annualized to a yearly figure and summed. These pin the per-span math, the page-total /
subtotal consistency, and that both render under the ids the antinode push targets.
"""
from collections import Counter
from dataclasses import replace
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from common.recurrence import Duration, TimeUnit

from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.recurring_expenses import RecurringExpensesForm
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets

_SECTION_TEMPLATE = 'inputs/interview/sections/recurring_expenses.html'
_MONTHLY = Duration( 1, TimeUnit.MONTH )


def _form_with_bands( per_band_amounts : list ) -> RecurringExpensesForm:
    """A Living form whose every expense carries `per_band_amounts` (one per span) at a monthly cadence,
    so the totals are fully determined. Reuses the seeded merged expenses as valid templates."""
    spans = [ 65, None ][ : len( per_band_amounts ) ] if len( per_band_amounts ) > 1 else [ None ]
    seed  = RecurringExpensesForm( profile = Profile(), plans = Plans( expense_spans = spans ) )
    rows  = [ replace( expense, amounts = list( per_band_amounts ), interval = _MONTHLY )
              for expense in seed._expenses ]
    return RecurringExpensesForm(
        profile = Profile(), plans = Plans( expense_spans = spans, recurring_expenses = rows ) )


class LivingExpenseTotalsTest( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()

    def test_page_total_is_every_expense_annualized_at_each_span( self ):
        form  = _form_with_bands( [ Decimal( '10' ), Decimal( '20' ) ] )
        count = len( form._expenses )
        self.assertEqual( form.totals_row[ 0 ].amount, Decimal( '10' ) * 12 * count )   # band 0: $10/mo each
        self.assertEqual( form.totals_row[ 1 ].amount, Decimal( '20' ) * 12 * count )   # band 1: $20/mo each

    def test_page_total_equals_the_sum_of_the_category_subtotals( self ):
        form = _form_with_bands( [ Decimal( '10' ), Decimal( '20' ) ] )
        for si in range( form.span_count ):
            subtotal_sum = sum( ( section[ 'subtotals' ][ si ].amount for section in form.sections ),
                                Decimal( 0 ) )
            self.assertEqual( form.totals_row[ si ].amount, subtotal_sum )

    def test_a_category_subtotal_is_its_own_rows_annualized( self ):
        form   = _form_with_bands( [ Decimal( '10' ) ] )
        counts = Counter( expense.category for expense in form._expenses )
        for section in form.sections:
            expected = counts[ section[ 'category' ] ] * Decimal( '10' ) * 12
            self.assertEqual( section[ 'subtotals' ][ 0 ].amount, expected )

    def test_the_total_and_subtotals_render_under_the_push_target_ids( self ):
        form = _form_with_bands( [ Decimal( '10' ) ] )
        html = render_to_string(
            _SECTION_TEMPLATE, { 'recurring_form': form, 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertIn( 'Living Expenses Total', html )
        self.assertIn( 'id="living-total-0"', html )                           # the page-total cell
        first_category = form.sections[ 0 ][ 'category' ].name.lower()
        self.assertIn( f'id="living-subtotal-{first_category}-0"', html )      # a category subtotal cell

    def test_multi_span_total_reserves_the_trend_arrow_spacer_for_alignment( self ):
        # Amount cells reserve a trailing (invisible) trend-arrow width; a total must reserve the same
        # spacer -- as a sibling after its value span, not inside it -- so its figure lines up with the
        # inputs and the antinode replace (which targets the value span) never duplicates the spacer.
        form = _form_with_bands( [ Decimal( '10' ), Decimal( '20' ) ] )
        html = render_to_string(
            _SECTION_TEMPLATE, { 'recurring_form': form, 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertRegex( html, r'id="living-total-0">[^<]*</span>\s*<span class="span-trend invisible"' )

    def test_single_span_total_omits_the_spacer( self ):
        # One column has no trend arrows on its amount cells, so the total needs no compensating spacer.
        form = _form_with_bands( [ Decimal( '10' ) ] )
        html = render_to_string(
            _SECTION_TEMPLATE, { 'recurring_form': form, 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertNotIn( 'span-trend', html )

    def test_totals_covers_every_subtotal_and_page_total( self ):
        # The flat push list is one subtotal per (category, span) plus one page total per span.
        form       = _form_with_bands( [ Decimal( '10' ), Decimal( '20' ) ] )
        categories = { expense.category for expense in form._expenses }
        expected   = form.span_count * ( len( categories ) + 1 )
        self.assertEqual( len( form.totals ), expected )
