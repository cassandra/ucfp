"""A subject's Retirement-plan `expected_lifetime` drives the engine's survivor transition -- it
materializes into the same `SubjectRemoval` the (retired) Death money-move produced. While both input
paths coexist (Phase 1), a subject is removed at most once, the lifetime taking precedence.
"""
import unittest
from datetime import date

from ucfp.forecast.parameters import SubjectRemoval
from ucfp.inputs.plans.schemas import Plans, RetirementTiming
from ucfp.planning.materialization import _lifetime_removals, _merged_subject_removals


class LifetimeRemovalTests( unittest.TestCase ):

    def test_a_set_expected_lifetime_becomes_a_subject_removal( self ):
        plans = Plans( timing = [ RetirementTiming(
            subject_handle = 'you', expected_lifetime = date( 2050, 6, 1 ) ) ] )
        removals = _lifetime_removals( plans )
        self.assertEqual( len( removals ), 1 )
        self.assertEqual( ( removals[ 0 ].subject_handle, removals[ 0 ].event_date ),
                          ( 'you', date( 2050, 6, 1 ) ) )

    def test_a_blank_expected_lifetime_yields_no_removal( self ):
        plans = Plans( timing = [ RetirementTiming( subject_handle = 'you' ) ] )
        self.assertEqual( _lifetime_removals( plans ), [] )


class MergedRemovalTests( unittest.TestCase ):

    def test_the_lifetime_wins_over_a_death_event_for_the_same_subject( self ):
        event = SubjectRemoval( event_date = date( 2040, 1, 1 ), subject_handle = 'you' )
        life  = SubjectRemoval( event_date = date( 2050, 6, 1 ), subject_handle = 'you' )
        merged = _merged_subject_removals( [ event ], [ life ] )
        self.assertEqual( len( merged ), 1 )                       # removed once, not twice
        self.assertEqual( merged[ 0 ].event_date, date( 2050, 6, 1 ) )   # the lifetime's date

    def test_removals_for_distinct_subjects_are_both_kept( self ):
        a = SubjectRemoval( event_date = date( 2040, 1, 1 ), subject_handle = 'you' )
        b = SubjectRemoval( event_date = date( 2050, 6, 1 ), subject_handle = 'partner' )
        self.assertEqual( len( _merged_subject_removals( [ a ], [ b ] ) ), 2 )
