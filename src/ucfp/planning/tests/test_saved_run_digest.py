"""_saved_run_digest: the cheap, cache-free display facts for a saved-run row.

Read straight from the captured run JSON (no books load), so the hub list is scannable -- year span and
whether the money lasted or the year it ran out. Robust by design: malformed or older-shaped data yields
None, and the row falls back to just its name and date rather than erroring.
"""
from django.test import SimpleTestCase

from ucfp.planning.views import _saved_run_digest


class _FakeRun:
    """A stand-in for a ProjectionRunRecord: only its `.data` JSON matters to the digest."""

    def __init__( self, data ):
        self.data = data


def _data( stopped_early = False, steps = None ):
    return {
        'frame'  : { 'start_date': '2026-01-01', 'end_date': '2065-12-31' },
        'result' : { 'stopped_early': stopped_early, 'steps': steps or [] },
    }


class SavedRunDigestTests( SimpleTestCase ):

    def test_lasting_run_reports_the_span_and_that_it_lasted( self ):
        digest = _saved_run_digest( _FakeRun( _data( stopped_early = False ) ) )
        self.assertEqual( digest, {
            'start_year': 2026, 'end_year': 2065, 'duration_years': 40,
            'lasted': True, 'ran_out_year': None } )

    def test_depleted_run_reports_the_year_the_money_ran_out( self ):
        steps  = [ { 'end_date': '2026-12-31', 'is_depleted': False },
                   { 'end_date': '2049-12-31', 'is_depleted': True } ]
        digest = _saved_run_digest( _FakeRun( _data( stopped_early = True, steps = steps ) ) )
        self.assertFalse( digest[ 'lasted' ] )
        self.assertEqual( digest[ 'ran_out_year' ], 2049 )

    def test_depleted_without_a_marked_step_still_reports_not_lasted( self ):
        # stopped_early but no is_depleted step: not lasted, but no year to name (defensive, not a crash).
        digest = _saved_run_digest( _FakeRun( _data( stopped_early = True, steps = [] ) ) )
        self.assertFalse( digest[ 'lasted' ] )
        self.assertIsNone( digest[ 'ran_out_year' ] )

    def test_missing_or_malformed_data_yields_none( self ):
        for data in ( {}, { 'frame': {} }, { 'frame': { 'start_date': 'nope', 'end_date': 'x' },
                                             'result': {} } ):
            self.assertIsNone( _saved_run_digest( _FakeRun( data ) ) )
