"""Tests for the process-local run-books cache.

The cache stands between the display views and the (costly) books reload, so what matters is that it
serves the *same* immutable graph for repeat views of a run, keys by the run's stable uuid (not a
reused primary key or object identity), and holds its memory bound by evicting the least-recently used
run. Correctness of the reload itself is the repository's; here we pin the caching behaviour.
"""
from django.test import TestCase

from organization.models import Organization

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.accounts.repository import BooksOfAccountRepository

from ucfp.planning.run_books_cache import (
    _MAX_CACHED_RUNS, clear_run_books_cache, load_run_books )


class RunBooksCacheTests( TestCase ):

    def setUp( self ):
        # The cache is process-global and outlives a single test, so start each from empty.
        clear_run_books_cache()
        self.organization = Organization.objects.create( name = 'Cache Org' )
        self.repository   = BooksOfAccountRepository()

    def _saved_books( self ) -> BooksOfAccountRecord:
        """A minimal saved books record (just the standard chart) -- enough to reload and cache."""
        bookkeeper = Bookkeeper()
        bookkeeper.build_standard_chart()
        return self.repository.save( bookkeeper.books, self.organization )

    def test_repeat_load_returns_the_same_cached_instance( self ):
        record = self._saved_books()
        first  = load_run_books( record )
        second = load_run_books( record )
        self.assertIs( first, second )

    def test_keyed_by_uuid_not_object_identity( self ):
        record   = self._saved_books()
        first    = load_run_books( record )
        # A distinct record instance for the same stored books (same uuid) must hit the same entry.
        refetched = BooksOfAccountRecord.objects.get( pk = record.pk )
        self.assertIs( load_run_books( refetched ), first )

    def test_reloads_match_the_repository( self ):
        record = self._saved_books()
        cached = load_run_books( record )
        direct = self.repository.load( record )
        self.assertEqual( len( cached.accounts ), len( direct.accounts ) )
        self.assertEqual( cached.label, direct.label )

    def test_lru_evicts_least_recently_used_beyond_the_bound( self ):
        records = [ self._saved_books() for _ in range( _MAX_CACHED_RUNS + 2 ) ]
        loaded  = [ load_run_books( record ) for record in records ]   # fills, then evicts the oldest two
        # The most-recent run stays warm (same instance); the oldest was evicted (fresh instance on reload).
        self.assertIs( load_run_books( records[ -1 ] ), loaded[ -1 ] )
        self.assertIsNot( load_run_books( records[ 0 ] ), loaded[ 0 ] )

    def test_clear_drops_every_entry( self ):
        record = self._saved_books()
        first  = load_run_books( record )
        clear_run_books_cache()
        self.assertIsNot( load_run_books( record ), first )
