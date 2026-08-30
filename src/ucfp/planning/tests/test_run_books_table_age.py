"""The sticky Age column in the run table: on yearly runs the Period column is joined by an Age column
showing the primary subject's true (whole-year) age at each interval end. It appears only when the run
is yearly (`show_age`) and a birthdate is known; the opening row shows the word 'opening' in place of its
date (so that text no longer widens the sticky Period column for every row). These tests render the
template with a synthetic set of rows and pin that behaviour.
"""
from datetime import date
from types import SimpleNamespace
from uuid import UUID

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from common.date_span import DateSpan
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.books_table import BooksTable, BooksTableRow
from ucfp.inputs.profile.schemas import SubjectProfile
from ucfp.planning.books_table import _age_column_context

_RUN_UUID  = UUID( '00000000-0000-0000-0000-0000000000aa' )
_BIRTHDATE = date( 1960, 6, 15 )              # a mid-year birthday: true age turns over mid-run

_OPENING = DateSpan( date( 2025, 12, 31 ), date( 2025, 12, 31 ) )   # the zero-length opening row
_PERIOD  = DateSpan( date( 2026, 1, 1 ), date( 2026, 12, 31 ) )     # the first real interval


def _table( *, show_age : bool, birthdate = _BIRTHDATE ) -> str:
    """The run table rendered over an opening row and one yearly interval, with no data columns (the
    Age/Period sticky pair is chrome, independent of the managed columns)."""
    rows = ( BooksTableRow( span = _OPENING, cells = () ),
             BooksTableRow( span = _PERIOD, cells = () ) )
    return render_to_string(
        'planning/pages/run_books_table.html',
        { 'record'        : SimpleNamespace( uuid = _RUN_UUID ),
          'books_table'   : BooksTable( columns = (), rows = rows ),
          'show_age'      : show_age,
          'age_birthdate' : birthdate },
        request = RequestFactory().get( '/' ) )


class RunBooksTableAgeColumnTest( SimpleTestCase ):

    def test_yearly_run_shows_an_age_header_and_true_age_per_interval( self ):
        html = _table( show_age = True )
        self.assertIn( '>Age</th>', html )
        # True age at each interval end: 65 at the 2025 opening (June birthday already past), 66 at 2026.
        self.assertIn( '<td class="bt-age-cell text-right text-nowrap">65</td>', html )
        self.assertIn( '<td class="bt-age-cell text-right text-nowrap">66</td>', html )

    def test_sub_annual_run_has_no_age_column( self ):
        html = _table( show_age = False )
        self.assertNotIn( '>Age</th>', html )
        self.assertNotIn( 'bt-age-cell', html )

    def test_opening_row_shows_opening_in_place_of_its_date( self ):
        html = _table( show_age = True )
        self.assertIn( '>opening</span>', html )
        self.assertNotIn( '2025-12', html )           # the opening date is replaced, not appended
        self.assertIn( '2026-12', html )              # a real interval still shows its date (YYYY-MM)

    def test_missing_birthdate_leaves_the_age_cells_blank( self ):
        html = _table( show_age = True, birthdate = None )
        self.assertIn( '>Age</th>', html )            # the column is still present...
        self.assertIn( '<td class="bt-age-cell text-right text-nowrap"></td>', html )   # ...but empty


def _run( granularity : Duration, subjects : list ) -> SimpleNamespace:
    """A stand-in run carrying only what the age-column derivation reads: the profile's subjects and
    the run frame's granularity."""
    return SimpleNamespace( profile = SimpleNamespace( subjects = subjects ),
                            frame   = SimpleNamespace( granularity = granularity ) )


class AgeColumnContextTest( SimpleTestCase ):
    """`_age_column_context` decides whether the Age column shows (yearly only) and whose birthdate it
    reads (the primary subject -- the household's first person)."""

    _SUBJECT = SubjectProfile( handle = 'subject', name = 'You', birthdate = _BIRTHDATE )

    def test_yearly_run_shows_age_for_the_primary_subject( self ):
        context = _age_column_context( _run( Duration( 1, TimeUnit.YEAR ), [ self._SUBJECT ] ) )
        self.assertTrue( context[ 'show_age' ] )
        self.assertEqual( context[ 'age_birthdate' ], _BIRTHDATE )

    def test_quarterly_and_monthly_runs_hide_the_age_column( self ):
        for granularity in ( Duration( 3, TimeUnit.MONTH ), Duration( 1, TimeUnit.MONTH ) ):
            context = _age_column_context( _run( granularity, [ self._SUBJECT ] ) )
            self.assertFalse( context[ 'show_age' ] )

    def test_primary_is_the_first_subject( self ):
        partner = SubjectProfile( handle = 'partner', name = 'Them', birthdate = date( 1962, 2, 3 ) )
        context = _age_column_context( _run( Duration( 1, TimeUnit.YEAR ), [ self._SUBJECT, partner ] ) )
        self.assertEqual( context[ 'age_birthdate' ], _BIRTHDATE )

    def test_no_subjects_yields_no_birthdate( self ):
        context = _age_column_context( _run( Duration( 1, TimeUnit.YEAR ), [] ) )
        self.assertIsNone( context[ 'age_birthdate' ] )
