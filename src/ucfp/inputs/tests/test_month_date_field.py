"""`MonthField` / `MonthDateInput`: the month-resolution date presentation for planning dates.

A month field solicits and shows `YYYY-MM` yet stores a real `date` normalized to the 15th (the
engine's mid-period convention). Its month-ness rides a `data-date-precision` attribute that is
orthogonal to the planning `context` -- a field can be both past-bounded and month-resolution.
"""
from datetime import date

from django import forms
from django.test import SimpleTestCase

from ucfp.environment.constants import AppConst
from ucfp.inputs.widgets import IsoDateInput, MonthDateInput, MonthField


class MonthFieldTests( SimpleTestCase ):

    def test_yyyy_mm_parses_to_the_fifteenth( self ):
        self.assertEqual( MonthField().clean( '2031-08' ), date( 2031, 8, 15 ) )

    def test_full_iso_is_not_accepted( self ):
        # The field solicits month resolution only; a day-precision string is a validation error, not a
        # silently-truncated value.
        with self.assertRaises( forms.ValidationError ):
            MonthField().clean( '2031-08-20' )

    def test_blank_is_none_when_optional( self ):
        self.assertIsNone( MonthField( required = False ).clean( '' ) )

    def test_blank_is_rejected_when_required( self ):
        with self.assertRaises( forms.ValidationError ):
            MonthField( required = True ).clean( '' )


class MonthDateInputTests( SimpleTestCase ):

    def _render( self, widget, value = None ) -> str:
        return widget.render( 'when', value )

    def test_existing_mid_month_value_renders_as_year_month( self ):
        # A stored day-precision date shows only its year and month; the day is hidden, not surfaced.
        html = self._render( MonthDateInput(), date( 2031, 8, 20 ) )
        self.assertIn( 'value="2031-08"', html )
        self.assertNotIn( '2031-08-20', html )

    def test_emits_both_context_and_precision_attributes( self ):
        # Past-bounded AND month-resolution: the two axes are independent and both must appear.
        html = self._render( MonthDateInput( context = AppConst.DATE_CONTEXT_PAST ) )
        self.assertIn( f'data-{AppConst.DATE_CONTEXT_DATA_ATTR}="{AppConst.DATE_CONTEXT_PAST}"', html )
        self.assertIn( f'data-{AppConst.DATE_PRECISION_DATA_ATTR}="{AppConst.DATE_PRECISION_MONTH}"', html )

    def test_day_input_carries_no_precision_attribute( self ):
        # The base day-resolution widget is unchanged: it must not emit a precision attribute at all.
        html = self._render( IsoDateInput() )
        self.assertNotIn( f'data-{AppConst.DATE_PRECISION_DATA_ATTR}', html )

    def test_round_trip_is_stable_at_month_resolution( self ):
        # clean() -> stored date -> re-render collapses back to the same YYYY-MM shown originally.
        stored = MonthField().clean( '2031-08' )
        html   = self._render( MonthDateInput(), stored )
        self.assertIn( 'value="2031-08"', html )
