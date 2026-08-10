"""The run-table column-action menu (#149 Part 3): a stable menu that does not reshuffle under the cursor.

Move left, Move right, Transaction history, and Hide always appear, disabled when they do not apply, so an
action keeps its place from one column to the next. Expand and Collapse are the deliberate exception -- a
column is one or the other, so only the applicable toggle shows (a leaf that is neither shows neither).
These tests render the template with a synthetic column and pin which menu items appear and which are
disabled.
"""
import re
from types import SimpleNamespace
from uuid import UUID

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from ucfp.accounts.books_table import (
    BooksColumnKey, BooksLeafColumn, BooksSummaryColumn, BooksTable, BooksTableColumn )

_RUN_UUID  = UUID( '00000000-0000-0000-0000-0000000000aa' )
_ACCT_UUID = UUID( '00000000-0000-0000-0000-0000000000bb' )


def _summary_column( **overrides ) -> BooksTableColumn:
    """A rollup column (no account, so no Transaction-history target) with edit flags overridable."""
    column = BooksSummaryColumn(
        key = BooksColumnKey( 'class:LIABILITY:vehicle-loans' ), label = 'Vehicle Loans',
        member_keys = ( BooksColumnKey( 'veh-1' ), ) )
    return _column( column, **overrides )


def _account_column( **overrides ) -> BooksTableColumn:
    """A leaf account column -- its key carries the UUID the Transaction-history link drills to."""
    column = BooksLeafColumn( key = BooksColumnKey.for_account( _ACCT_UUID ), label = 'Civic loan' )
    return _column( column, **overrides )


def _column( column, **overrides ) -> BooksTableColumn:
    fields = dict(
        op_key = column.key, expand_key = column.key, removed = False, can_expand = False,
        can_collapse = False, depth = 1, group = 'liability', can_move_left = True,
        can_move_right = True, breadcrumb = () )
    fields.update( overrides )
    return BooksTableColumn( column = column, **fields )


def _menu( col : BooksTableColumn ) -> str:
    """The table rendered around a single column -- a request is supplied so `{% csrf_token %}` resolves."""
    return render_to_string(
        'planning/pages/run_books_table.html',
        { 'record' : SimpleNamespace( uuid = _RUN_UUID ), 'books_table' : BooksTable( ( col, ), () ) },
        request = RequestFactory().get( '/' ) )


def _button( html : str, label : str ) -> str:
    """The `<button>…label…</button>` for a menu action -- matched whole so a test reads its attributes
    (e.g. `disabled`) without coupling to attribute order or the template's line wrapping. '' if absent."""
    match = re.search( r'<button[^>]*>' + re.escape( label ) + r'</button>', html )
    return match.group( 0 ) if match else ''


class ColumnMenuIsStableTest( SimpleTestCase ):

    def test_move_actions_always_render_disabled_at_a_group_edge( self ):
        html = _menu( _summary_column( can_move_left = False, can_move_right = True ) )
        self.assertIn( 'disabled', _button( html, 'Move left' ) )      # both present, the edge one disabled
        self.assertNotIn( 'disabled', _button( html, 'Move right' ) )

    def test_move_actions_are_enabled_off_an_edge( self ):
        html = _menu( _account_column( can_move_left = True, can_move_right = True ) )
        self.assertNotIn( 'disabled', _button( html, 'Move left' ) )
        self.assertNotIn( 'disabled', _button( html, 'Move right' ) )

    def test_transaction_history_is_a_disabled_item_without_an_account( self ):
        html = _menu( _summary_column() )                      # a summary has no account to drill
        self.assertIn( 'Transaction history</span>', html )    # shown, as a disabled span...
        self.assertNotIn( 'Transaction history</a>', html )    # ...not a live link

    def test_transaction_history_links_for_an_account_column( self ):
        html = _menu( _account_column() )
        self.assertIn( 'Transaction history</a>', html )

    def test_hide_is_always_present( self ):
        self.assertIn( '>Hide<', _menu( _summary_column() ) )
        self.assertIn( '>Hide<', _menu( _account_column() ) )

    def test_only_expand_shows_when_the_column_is_expandable( self ):
        html = _menu( _summary_column( can_expand = True, can_collapse = False ) )
        self.assertIn( '>Expand<', html )
        self.assertNotIn( '>Collapse<', html )

    def test_only_collapse_shows_when_the_column_is_expanded( self ):
        html = _menu( _summary_column( can_expand = False, can_collapse = True ) )
        self.assertIn( '>Collapse<', html )
        self.assertNotIn( '>Expand<', html )

    def test_a_leaf_shows_neither_expand_nor_collapse( self ):
        html = _menu( _account_column( can_expand = False, can_collapse = False ) )
        self.assertNotIn( '>Expand<', html )
        self.assertNotIn( '>Collapse<', html )
