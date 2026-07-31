"""The collision-free auto-naming helpers (`numbered_label`, `unique_label`).

Pure, dependency-free logic that three repositories (Plans, Assumptions, Scenarios) rely on for default
and clone names, so a regression would silently produce colliding names in several places. Worth pinning
even in the minimal-testing phase: the search loops, case-insensitive comparison, and the base-free vs
suffixed distinction each have a non-obvious edge.
"""
from django.test import SimpleTestCase

from ucfp.inputs.naming import numbered_label, unique_label


class NumberedLabelTest( SimpleTestCase ):

    def test_counts_from_one_when_none_taken( self ):
        self.assertEqual( numbered_label( 'Plans', [] ), 'Plans 1' )

    def test_next_after_contiguous( self ):
        self.assertEqual( numbered_label( 'Plans', [ 'Plans 1', 'Plans 2' ] ), 'Plans 3' )

    def test_fills_the_lowest_free_number( self ):
        self.assertEqual( numbered_label( 'Plans', [ 'Plans 1', 'Plans 3' ] ), 'Plans 2' )

    def test_comparison_is_case_insensitive( self ):
        self.assertEqual( numbered_label( 'Plans', [ 'plans 1' ] ), 'Plans 2' )

    def test_ignores_labels_of_other_prefixes( self ):
        self.assertEqual( numbered_label( 'Plans', [ 'Assumptions 1', 'Custom' ] ), 'Plans 1' )


class UniqueLabelTest( SimpleTestCase ):

    def test_returns_base_when_free( self ):
        self.assertEqual( unique_label( 'Plans copy', [] ), 'Plans copy' )

    def test_suffix_starts_at_two( self ):
        self.assertEqual( unique_label( 'Plans copy', [ 'Plans copy' ] ), 'Plans copy 2' )

    def test_skips_taken_suffixes( self ):
        self.assertEqual(
            unique_label( 'Plans copy', [ 'Plans copy', 'Plans copy 2' ] ), 'Plans copy 3' )

    def test_comparison_is_case_insensitive( self ):
        self.assertEqual( unique_label( 'Plans copy', [ 'plans copy' ] ), 'Plans copy 2' )

    def test_no_suffix_when_base_free_even_if_suffixed_form_exists( self ):
        self.assertEqual( unique_label( 'Plans copy', [ 'Plans copy 2' ] ), 'Plans copy' )
