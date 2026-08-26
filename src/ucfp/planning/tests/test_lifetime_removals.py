"""A subject's Retirement-plan `expected_lifetime` drives the engine's survivor transition -- it
materializes into the `SubjectRemoval` the (retired) Death money-move used to produce, one per subject
whose lifetime is set (blank = death not modeled).
"""
import unittest
from datetime import date

from ucfp.inputs.plans.schemas import Plans, RetirementTiming
from ucfp.planning.materialization import _lifetime_removals


class LifetimeRemovalTests( unittest.TestCase ):

    def test_a_set_expected_lifetime_becomes_a_subject_removal( self ):
        plans = Plans( timing = [
            RetirementTiming( subject_handle = 'you', expected_lifetime = date( 2050, 6, 1 ) ),
            RetirementTiming( subject_handle = 'partner' ) ] )   # partner's blank -> no removal
        removals = _lifetime_removals( plans )
        self.assertEqual( len( removals ), 1 )
        self.assertEqual( ( removals[ 0 ].subject_handle, removals[ 0 ].event_date ),
                          ( 'you', date( 2050, 6, 1 ) ) )

    def test_no_expected_lifetime_yields_no_removal( self ):
        plans = Plans( timing = [ RetirementTiming( subject_handle = 'you' ) ] )
        self.assertEqual( _lifetime_removals( plans ), [] )
