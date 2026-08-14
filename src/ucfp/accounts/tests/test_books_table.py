"""`BooksTableDefinition.adapt` (#108): revealing columns that appear after the lens was set.

`adapt` fits a stored session lens to a run's catalog. Besides dropping columns the run lacks, it must
reveal a catalog member that showed up later (e.g. a partner's income once the subject exists) under an
already-expanded summary -- added collapsed, so the user explicitly expands it -- while leaving collapsed
groups, removals, and the existing order untouched. A synthetic catalog (source -> subject -> leaf, the
shape of income columns) exercises the reveal without a full forecast.
"""
import unittest
from datetime import date
from decimal import Decimal
from uuid import UUID

from common.date_span import DateSpan

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, AssetClass, SystemAccountRole
from ucfp.accounts.books_table import (
    BooksColumnKey, BooksDerivedFigure, BooksLeafColumn, BooksSummaryColumn, BooksTableColumn,
    BooksTableColumnCatalog, BooksTableDefinition, _empty_op_keys, _render_columns, build_books_table )


def _summary( token, members, parent = None ):
    return BooksSummaryColumn(
        key = BooksColumnKey( token ), label = token,
        parent_key = BooksColumnKey( parent ) if parent is not None else None,
        member_keys = tuple( BooksColumnKey( member ) for member in members ) )


def _leaf( token, parent ):
    return BooksLeafColumn( key = BooksColumnKey( token ), label = token,
                            parent_key = BooksColumnKey( parent ) )


def _account_leaf( uuid : UUID, parent, label ):
    """An account-kind leaf -- its key carries the account UUID the Journal drill reads."""
    return BooksLeafColumn( key = BooksColumnKey.for_account( uuid ), label = label,
                            parent_key = BooksColumnKey( parent ) )


def _couple_catalog():
    """Income -> a Social Security source -> a subject rung per person -> the account leaf, for a couple."""
    return BooksTableColumnCatalog( [
        _summary( 'type:INCOME', [ 'src:ss' ] ),
        _summary( 'src:ss', [ 'subj:you', 'subj:partner' ], parent = 'type:INCOME' ),
        _summary( 'subj:you', [ 'acct:you' ], parent = 'src:ss' ),
        _leaf( 'acct:you', 'subj:you' ),
        _summary( 'subj:partner', [ 'acct:partner' ], parent = 'src:ss' ),
        _leaf( 'acct:partner', 'subj:partner' ) ] )


def _tokens( definition ):
    return [ key.token for key in definition.column_keys ]


class AdaptRevealsNewColumnsTest( unittest.TestCase ):

    def test_new_member_of_an_expanded_summary_is_revealed_collapsed_at_the_group_tail( self ):
        # a lens built when only 'you' existed, expanded to your Social Security leaf
        lens    = BooksTableDefinition( _keys( 'type:INCOME', 'src:ss', 'subj:you', 'acct:you' ) )
        adapted = lens.adapt( _couple_catalog() )
        # the source is expanded (a subject is shown), so the partner's rung is revealed...
        self.assertEqual(
            _tokens( adapted ),
            [ 'type:INCOME', 'src:ss', 'subj:you', 'acct:you', 'subj:partner' ] )
        # ...collapsed: the partner's leaf is NOT pulled in (the user expands to reach it)
        self.assertNotIn( 'acct:partner', _tokens( adapted ) )

    def test_a_collapsed_summary_reveals_nothing( self ):
        # the source is present but collapsed (no subject shown), so no subject is revealed under it
        lens    = BooksTableDefinition( _keys( 'type:INCOME', 'src:ss' ) )
        adapted = lens.adapt( _couple_catalog() )
        self.assertEqual( _tokens( adapted ), [ 'type:INCOME', 'src:ss' ] )

    def test_no_newcomers_leaves_the_frontier_unchanged( self ):
        keys    = _keys( 'type:INCOME', 'src:ss', 'subj:you', 'acct:you',
                         'subj:partner', 'acct:partner' )
        adapted = BooksTableDefinition( keys ).adapt( _couple_catalog() )
        self.assertEqual( adapted.column_keys, keys )

    def test_a_removed_column_stays_removed_and_a_newcomer_is_still_revealed( self ):
        lens = BooksTableDefinition(
            _keys( 'type:INCOME', 'src:ss', 'subj:you' ),
            removed_keys = _keys( 'subj:you' ) )
        adapted = lens.adapt( _couple_catalog() )
        self.assertIn( 'subj:partner', _tokens( adapted ) )                          # newcomer revealed
        self.assertEqual( adapted.removed_keys, _keys( 'subj:you' ) )                # removal preserved
        self.assertNotIn( BooksColumnKey( 'subj:partner' ), adapted.removed_keys )   # newcomer not removed

    def test_columns_the_run_lacks_are_dropped( self ):
        # a stale column (a prior run's account) is filtered out, as before
        lens    = BooksTableDefinition( _keys( 'type:INCOME', 'src:ss', 'subj:you', 'acct:stale' ) )
        adapted = lens.adapt( _couple_catalog() )
        self.assertNotIn( 'acct:stale', _tokens( adapted ) )

    def test_a_newcomer_lands_after_a_populated_sibling_block_not_mid_subtree( self ):
        # 'you' is drilled to two accounts and both the type and source are expanded; the partner rung
        # is the newcomer and must land at the SOURCE's group tail -- after the whole 'you' block, not
        # spliced mid-subtree (the group-tail computation walking past a populated sibling).
        catalog = BooksTableColumnCatalog( [
            _summary( 'type:INCOME', [ 'src:ss' ] ),
            _summary( 'src:ss', [ 'subj:you', 'subj:partner' ], parent = 'type:INCOME' ),
            _summary( 'subj:you', [ 'acct:you1', 'acct:you2' ], parent = 'src:ss' ),
            _leaf( 'acct:you1', 'subj:you' ),
            _leaf( 'acct:you2', 'subj:you' ),
            _summary( 'subj:partner', [ 'acct:partner' ], parent = 'src:ss' ),
            _leaf( 'acct:partner', 'subj:partner' ) ] )
        lens    = BooksTableDefinition(
            _keys( 'type:INCOME', 'src:ss', 'subj:you', 'acct:you1', 'acct:you2' ) )
        adapted = lens.adapt( catalog )
        self.assertEqual(
            _tokens( adapted ),
            [ 'type:INCOME', 'src:ss', 'subj:you', 'acct:you1', 'acct:you2', 'subj:partner' ] )

    def test_multiple_newcomers_append_in_member_order_at_the_group_tail( self ):
        catalog = BooksTableColumnCatalog( [
            _summary( 'type:INCOME', [ 'src:ss' ] ),
            _summary( 'src:ss', [ 'subj:you', 'subj:a', 'subj:b' ], parent = 'type:INCOME' ),
            _summary( 'subj:you', [ 'acct:you' ], parent = 'src:ss' ),
            _leaf( 'acct:you', 'subj:you' ),
            _summary( 'subj:a', [ 'acct:a' ], parent = 'src:ss' ),
            _leaf( 'acct:a', 'subj:a' ),
            _summary( 'subj:b', [ 'acct:b' ], parent = 'src:ss' ),
            _leaf( 'acct:b', 'subj:b' ) ] )
        lens    = BooksTableDefinition( _keys( 'type:INCOME', 'src:ss', 'subj:you', 'acct:you' ) )
        adapted = lens.adapt( catalog )
        self.assertEqual(
            _tokens( adapted ),
            [ 'type:INCOME', 'src:ss', 'subj:you', 'acct:you', 'subj:a', 'subj:b' ] )


def _keys( *tokens ):
    return tuple( BooksColumnKey( token ) for token in tokens )


_LOAN_UUID = UUID( '00000000-0000-0000-0000-000000000001' )


def _one_loan_catalog():
    """Liabilities with two classes; the Vehicle Loans class holds one vehicle whose one loan makes a
    single-child chain (class -> vehicle -> loan account) down to a leaf, beside a plain Mortgage leaf."""
    return BooksTableColumnCatalog( [
        _summary( 'type:LIABILITY', [ 'vehicle-loans', 'mortgage' ] ),
        _summary( 'vehicle-loans', [ 'veh-1' ], parent = 'type:LIABILITY' ),
        _summary( 'veh-1', [ BooksColumnKey.for_account( _LOAN_UUID ).token ], parent = 'vehicle-loans' ),
        _account_leaf( _LOAN_UUID, 'veh-1', 'Civic loan' ),
        _leaf( 'mortgage', 'type:LIABILITY' ) ] )


def _two_loan_catalog():
    """A Vehicle Loans class whose one vehicle has two loans: the single-child chain (class -> vehicle)
    terminates at the branching vehicle rung, which keeps its own expand."""
    return BooksTableColumnCatalog( [
        _summary( 'type:LIABILITY', [ 'vehicle-loans' ] ),
        _summary( 'vehicle-loans', [ 'veh-1' ], parent = 'type:LIABILITY' ),
        _summary( 'veh-1', [ 'loan-a', 'loan-b' ], parent = 'vehicle-loans' ),
        _leaf( 'loan-a', 'veh-1' ),
        _leaf( 'loan-b', 'veh-1' ) ] )


def _two_vehicle_catalog():
    """One Vehicle Loans class with two vehicles, each a single-child chain to its own loan leaf -- the
    reorder case: moving a vehicle's rung must carry that vehicle's loan leaf with it."""
    return BooksTableColumnCatalog( [
        _summary( 'type:LIABILITY', [ 'vehicle-loans' ] ),
        _summary( 'vehicle-loans', [ 'veh-1', 'veh-2' ], parent = 'type:LIABILITY' ),
        _summary( 'veh-1', [ 'loan-1' ], parent = 'vehicle-loans' ),
        _leaf( 'loan-1', 'veh-1' ),
        _summary( 'veh-2', [ 'loan-2' ], parent = 'vehicle-loans' ),
        _leaf( 'loan-2', 'veh-2' ) ] )


def _shared_label_catalog():
    """A single-child chain whose vehicle rung and terminal loan leaf carry the SAME label ('Civic'), to
    exercise the breadcrumb's drop-the-duplicate-of-the-terminal step."""
    return BooksTableColumnCatalog( [
        BooksSummaryColumn( key = BooksColumnKey( 'type:LIABILITY' ), label = 'Liabilities',
                            member_keys = ( BooksColumnKey( 'vehicle-loans' ), ) ),
        BooksSummaryColumn( key = BooksColumnKey( 'vehicle-loans' ), label = 'Vehicle Loans',
                            parent_key = BooksColumnKey( 'type:LIABILITY' ),
                            member_keys = ( BooksColumnKey( 'veh-1' ), ) ),
        BooksSummaryColumn( key = BooksColumnKey( 'veh-1' ), label = 'Civic',
                            parent_key = BooksColumnKey( 'vehicle-loans' ),
                            member_keys = ( BooksColumnKey.for_account( _LOAN_UUID ), ) ),
        BooksLeafColumn( key = BooksColumnKey.for_account( _LOAN_UUID ), label = 'Civic',
                         parent_key = BooksColumnKey( 'veh-1' ) ) ] )


def _rendered_by_op( columns ):
    return { column.op_key.token : column for column in columns }


class RenderCompressesSingleChildChainsTest( unittest.TestCase ):
    """A single-child grouping chain renders as its terminal alone (no dead-end expand), the absorbed
    rungs a breadcrumb -- while the top-level type total stays its own column."""

    def test_single_child_chain_to_a_leaf_renders_as_the_account_no_dead_end_expand( self ):
        catalog    = _one_loan_catalog()
        definition = BooksTableDefinition( _keys( 'type:LIABILITY', 'vehicle-loans', 'mortgage' ) )
        rendered   = _rendered_by_op( _render_columns( catalog, definition ) )
        vehicle    = rendered[ 'vehicle-loans' ]
        # The class/vehicle rungs collapse away: the loan account itself is what shows.
        self.assertEqual( vehicle.column.account_uuid, _LOAN_UUID )   # its Journal is reachable collapsed
        self.assertFalse( vehicle.can_expand )                        # a leaf -- no dead-end drill
        self.assertFalse( vehicle.can_collapse )
        self.assertEqual( vehicle.breadcrumb, ( 'vehicle-loans', 'veh-1' ) )
        self.assertEqual( vehicle.expand_key, BooksColumnKey.for_account( _LOAN_UUID ) )

    def test_the_type_total_is_not_compressed_away( self ):
        catalog    = _two_loan_catalog()                             # type:LIABILITY has a single child
        definition = BooksTableDefinition( _keys( 'type:LIABILITY' ) )
        rendered   = _rendered_by_op( _render_columns( catalog, definition ) )
        liabilities = rendered[ 'type:LIABILITY' ]
        self.assertEqual( liabilities.column.key, BooksColumnKey( 'type:LIABILITY' ) )   # stays a column
        self.assertTrue( liabilities.can_expand )

    def test_single_child_chain_to_a_branching_rung_keeps_that_rungs_expand( self ):
        catalog    = _two_loan_catalog()
        definition = BooksTableDefinition( _keys( 'type:LIABILITY', 'vehicle-loans' ) )
        rendered   = _rendered_by_op( _render_columns( catalog, definition ) )
        vehicle    = rendered[ 'vehicle-loans' ]
        self.assertEqual( vehicle.column.key, BooksColumnKey( 'veh-1' ) )   # the branching terminal shows
        self.assertTrue( vehicle.can_expand )                              # ...still expandable
        self.assertEqual( vehicle.breadcrumb, ( 'vehicle-loans', ) )
        self.assertEqual( vehicle.expand_key, BooksColumnKey( 'veh-1' ) )

    def test_expanding_a_compressed_branching_terminal_reveals_its_members( self ):
        catalog    = _two_loan_catalog()
        definition = BooksTableDefinition( _keys( 'type:LIABILITY', 'vehicle-loans' ) )
        # The terminal (veh-1) is not itself on the frontier -- expand still splices its loans in, after
        # the chain's present top (vehicle-loans).
        expanded = definition.expand( catalog, BooksColumnKey( 'veh-1' ) )
        self.assertEqual(
            _tokens( expanded ), [ 'type:LIABILITY', 'vehicle-loans', 'loan-a', 'loan-b' ] )
        rendered = _rendered_by_op( _render_columns( catalog, expanded ) )
        self.assertTrue( rendered[ 'vehicle-loans' ].can_collapse )        # now foldable
        self.assertIn( 'loan-a', rendered )                                # the loans show individually
        self.assertIn( 'loan-b', rendered )

    def test_collapsing_the_chain_top_folds_the_revealed_loans_back( self ):
        catalog  = _two_loan_catalog()
        expanded = BooksTableDefinition(
            _keys( 'type:LIABILITY', 'vehicle-loans', 'loan-a', 'loan-b' ) )
        folded   = expanded.collapse( catalog, BooksColumnKey( 'vehicle-loans' ) )
        self.assertEqual( _tokens( folded ), [ 'type:LIABILITY', 'vehicle-loans' ] )

    def test_a_breadcrumb_rung_matching_the_terminal_label_is_dropped( self ):
        # veh-1's rung and its one loan leaf both read 'Civic'; the crumb keeps 'Vehicle Loans' but drops
        # the 'Civic' that would merely repeat the column's own label.
        rendered = _rendered_by_op(
            _render_columns( _shared_label_catalog(),
                             BooksTableDefinition( _keys( 'type:LIABILITY', 'vehicle-loans' ) ) ) )
        self.assertEqual( rendered[ 'vehicle-loans' ].breadcrumb, ( 'Vehicle Loans', ) )

    def test_expand_and_collapse_are_never_both_offered( self ):
        # The Part-3 premise: a column is expandable or collapsed, never both -- across collapsed, drilled,
        # and leaf states of a chain.
        catalog = _two_loan_catalog()
        for definition in ( BooksTableDefinition( _keys( 'type:LIABILITY' ) ),
                            BooksTableDefinition( _keys( 'type:LIABILITY', 'vehicle-loans' ) ),
                            BooksTableDefinition(
                                _keys( 'type:LIABILITY', 'vehicle-loans', 'loan-a', 'loan-b' ) ) ):
            for column in _render_columns( catalog, definition ):
                self.assertFalse( column.can_expand and column.can_collapse,
                                  f'{column.op_key.token} offers both expand and collapse' )


class CompressedChainStructuralOpsTest( unittest.TestCase ):
    """Move and Hide act on a compressed chain's TOP (`op_key`) while it displays its terminal -- so the
    ops carry the whole chain and mark it at the top, not at the absorbed terminal."""

    def test_reordering_a_per_vehicle_rung_carries_its_loan_leaf( self ):
        definition = BooksTableDefinition(
            _keys( 'type:LIABILITY', 'vehicle-loans', 'veh-1', 'loan-1', 'veh-2', 'loan-2' ) )
        moved = definition.move( _two_vehicle_catalog(), BooksColumnKey( 'veh-1' ), +1 )
        self.assertEqual(                                        # veh-1's loan travels with its rung
            _tokens( moved ),
            [ 'type:LIABILITY', 'vehicle-loans', 'veh-2', 'loan-2', 'veh-1', 'loan-1' ] )

    def test_reorder_is_a_no_op_at_the_group_edge( self ):
        definition = BooksTableDefinition(
            _keys( 'type:LIABILITY', 'vehicle-loans', 'veh-1', 'loan-1', 'veh-2', 'loan-2' ) )
        self.assertEqual( definition.move( _two_vehicle_catalog(), BooksColumnKey( 'veh-2' ), +1 ),
                          definition )

    def test_hiding_a_compressed_chain_slivers_the_top_not_the_terminal_account( self ):
        catalog    = _one_loan_catalog()
        definition = BooksTableDefinition( _keys( 'type:LIABILITY', 'vehicle-loans', 'mortgage' ) )
        rendered   = _rendered_by_op(
            _render_columns( catalog, definition.remove( catalog, BooksColumnKey( 'vehicle-loans' ) ) ) )
        self.assertTrue( rendered[ 'vehicle-loans' ].removed )                     # the chain top is hidden
        self.assertNotIn( BooksColumnKey.for_account( _LOAN_UUID ).token, rendered )   # not the loan account
        self.assertEqual( [ c for c in rendered.values() if c.removed ],
                          [ rendered[ 'vehicle-loans' ] ] )                        # exactly one sliver


class RevealedKeysTest( unittest.TestCase ):
    """`revealed_keys`: the opt-out of automatic empty-column hiding. It rides the lens's storage, `adapt`
    trims keys the run lacks, and every structural op carries it through unchanged."""

    def test_reveal_adds_a_key_and_is_idempotent( self ):
        lens     = BooksTableDefinition( _keys( 'a', 'b' ) )
        revealed = lens.reveal( BooksColumnKey( 'a' ) )
        self.assertEqual( revealed.revealed_keys, _keys( 'a' ) )
        self.assertIs( revealed.reveal( BooksColumnKey( 'a' ) ), revealed )   # already revealed -> same lens

    def test_storage_round_trips_revealed_keys( self ):
        lens     = BooksTableDefinition( _keys( 'a', 'b' ), _keys( 'b' ), _keys( 'a' ) )
        restored = BooksTableDefinition.from_storage( lens.to_storage() )
        self.assertEqual( restored.revealed_keys, _keys( 'a' ) )
        self.assertEqual( restored.removed_keys, _keys( 'b' ) )

    def test_a_legacy_lens_without_revealed_reads_as_empty( self ):
        restored = BooksTableDefinition.from_storage( { 'columns' : [ 'a' ], 'removed' : [] } )
        self.assertEqual( restored.revealed_keys, () )

    def test_adapt_drops_revealed_keys_the_run_lacks( self ):
        lens    = BooksTableDefinition( _keys( 'type:INCOME' ),
                                        revealed_keys = _keys( 'acct:you', 'acct:gone' ) )
        adapted = lens.adapt( _couple_catalog() )
        self.assertEqual( adapted.revealed_keys, _keys( 'acct:you' ) )        # 'acct:gone' is not in the run

    def test_structural_ops_carry_revealed_keys_through( self ):
        catalog  = _couple_catalog()
        revealed = _keys( 'acct:you' )
        lens     = BooksTableDefinition( _keys( 'type:INCOME' ), revealed_keys = revealed )
        expanded = lens.expand( catalog, BooksColumnKey( 'type:INCOME' ) )
        self.assertEqual( expanded.revealed_keys, revealed )
        self.assertEqual( expanded.remove( catalog, BooksColumnKey( 'src:ss' ) ).revealed_keys, revealed )
        self.assertEqual( expanded.collapse( catalog, BooksColumnKey( 'type:INCOME' ) ).revealed_keys,
                          revealed )
        self.assertEqual( lens.restore( BooksColumnKey( 'x' ) ).revealed_keys, revealed )


def _rendered( column, removed = False ):
    """A minimal rendered column standing on its own key -- enough for the emptiness test."""
    return BooksTableColumn( column = column, op_key = column.key, expand_key = column.key,
                             removed = removed )


_ACCT_A = UUID( '00000000-0000-0000-0000-0000000000a1' )


class EmptyColumnDetectionTest( unittest.TestCase ):
    """`_empty_op_keys`: which columns auto-hide. Only an account leaf the user has not revealed whose
    figure reads as zero (under half a cent) in every period; summaries, derived figures, revealed
    columns, and columns with any activity stay."""

    def test_an_all_zero_account_leaf_is_hidden( self ):
        col = _rendered( _account_leaf( _ACCT_A, 'p', 'Idle' ) )
        self.assertEqual(
            _empty_op_keys( ( col, ), { col.op_key : ( Decimal( '0' ), Decimal( '0' ) ) }, set() ),
            { col.op_key } )

    def test_any_period_with_activity_keeps_it( self ):
        col = _rendered( _account_leaf( _ACCT_A, 'p', 'Active' ) )
        self.assertEqual(
            _empty_op_keys( ( col, ), { col.op_key : ( Decimal( '0' ), Decimal( '500' ) ) }, set() ),
            set() )

    def test_a_sub_cent_residual_still_counts_as_empty( self ):
        col = _rendered( _account_leaf( _ACCT_A, 'p', 'Residual' ) )
        self.assertEqual(
            _empty_op_keys( ( col, ), { col.op_key : ( Decimal( '0' ), Decimal( '0.004' ) ) }, set() ),
            { col.op_key } )

    def test_a_revealed_account_is_kept( self ):
        col = _rendered( _account_leaf( _ACCT_A, 'p', 'Idle' ) )
        self.assertEqual(
            _empty_op_keys( ( col, ), { col.op_key : ( Decimal( '0' ), ) }, { col.op_key } ), set() )

    def test_a_zero_summary_total_is_not_hidden( self ):
        col = _rendered( _summary( 'type:ASSET', [ 'a' ] ) )
        self.assertEqual( _empty_op_keys( ( col, ), { col.op_key : ( Decimal( '0' ), ) }, set() ), set() )

    def test_a_zero_derived_figure_is_not_hidden( self ):
        col = _rendered( BooksLeafColumn(
            key = BooksColumnKey.for_derived( BooksDerivedFigure.NET_WORTH ), label = 'Net worth' ) )
        self.assertEqual( _empty_op_keys( ( col, ), { col.op_key : ( Decimal( '0' ), ) }, set() ), set() )

    def test_a_removed_account_is_left_to_its_removal( self ):
        col = _rendered( _account_leaf( _ACCT_A, 'p', 'Idle' ), removed = True )
        self.assertEqual( _empty_op_keys( ( col, ), {}, set() ), set() )   # removed -> not even in the series


class BuildBooksTableEmptyColumnsTest( unittest.TestCase ):
    """End to end through `build_books_table`: a funded-then-idle account keeps its column (its balance
    persists), an account that never sees activity auto-hides, and revealing it brings it back."""

    def _books( self ):
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        chart      = bookkeeper.chart
        asset_root = chart.root( AccountType.ASSET )
        cash       = bookkeeper.create_holding( asset_root, 'Cash', AssetClass.CASH )
        unused     = bookkeeper.create_holding( asset_root, 'Unused', AssetClass.STOCKS )
        opening    = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        # Fund Cash once at t0 and never again; Unused is created but never touched.
        bookkeeper.record( date( 2026, 1, 1 ),
                           [ ( cash, Decimal( '-100000' ) ), ( opening, Decimal( '100000' ) ) ],
                           description = 'Opening' )
        return bookkeeper, chart, cash, unused

    def test_idle_account_hides_funded_stays_and_reveal_restores( self ):
        bookkeeper, chart, cash, unused = self._books()
        catalog    = BooksTableColumnCatalog.build( chart )
        cash_key   = BooksColumnKey.for_account( cash.account_uuid )
        unused_key = BooksColumnKey.for_account( unused.account_uuid )
        definition = BooksTableDefinition( ( cash_key, unused_key ) )
        spans      = [ DateSpan( date( 2026, 1, 1 ), date( 2026, 12, 31 ) ),
                       DateSpan( date( 2027, 1, 1 ), date( 2027, 12, 31 ) ) ]

        table = build_books_table( bookkeeper.ledger, chart, spans, definition, catalog )
        empty = { column.column.label : column.empty for column in table.columns }
        self.assertFalse( empty[ 'Cash' ] )      # funded once, idle after -> balance persists -> stays
        self.assertTrue( empty[ 'Unused' ] )     # never any activity -> auto-hidden

        revealed = build_books_table(
            bookkeeper.ledger, chart, spans, definition.reveal( unused_key ), catalog )
        self.assertFalse( { c.column.label : c.empty for c in revealed.columns }[ 'Unused' ] )


if __name__ == '__main__':
    unittest.main()
