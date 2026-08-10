"""`BooksTableDefinition.adapt` (#108): revealing columns that appear after the lens was set.

`adapt` fits a stored session lens to a run's catalog. Besides dropping columns the run lacks, it must
reveal a catalog member that showed up later (e.g. a partner's income once the subject exists) under an
already-expanded summary -- added collapsed, so the user explicitly expands it -- while leaving collapsed
groups, removals, and the existing order untouched. A synthetic catalog (source -> subject -> leaf, the
shape of income columns) exercises the reveal without a full forecast.
"""
import unittest
from uuid import UUID

from ucfp.accounts.books_table import (
    BooksColumnKey, BooksLeafColumn, BooksSummaryColumn, BooksTableColumnCatalog,
    BooksTableDefinition, _render_columns )


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


if __name__ == '__main__':
    unittest.main()
