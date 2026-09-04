"""Restating a run's nominal figures in start-year ("today's") dollars: the shared deflation used by the
run-summary "Today's $" figure and the charts, so they cannot disagree. Deflation is by the run's constant
general-inflation assumption compounded over whole calendar years from the run's start.
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from common.rate import Rate

from ucfp.planning.inflation import deflation_factor, to_todays_dollars


def _run( start_year = 2026, inflation = Decimal( '0' ), *, has_assumptions = True ):
    """A minimal run stand-in: its frame start year and captured general-inflation rate -- the only fields
    the deflation reads. `has_assumptions=False` models a run with no assumptions set (reads as zero)."""
    assumptions = ( SimpleNamespace( economics = SimpleNamespace( inflation = Rate( inflation ) ) )
                    if has_assumptions else None )
    return SimpleNamespace( frame = SimpleNamespace( start_date = date( start_year, 1, 1 ) ),
                            assumptions = assumptions )


class ToTodaysDollarsTests( unittest.TestCase ):

    def test_deflates_by_cumulative_inflation( self ):
        got = to_todays_dollars( _run( 2026, Decimal( '0.035' ) ), Decimal( '500000' ), date( 2036, 1, 1 ) )
        self.assertEqual( got, Decimal( '500000' ) / ( Decimal( '1.035' ) ** 10 ) )   # 10 whole years
        self.assertLess( got, Decimal( '500000' ) )

    def test_none_for_zero_inflation( self ):
        self.assertIsNone(
            to_todays_dollars( _run( 2026, Decimal( '0' ) ), Decimal( '100' ), date( 2036, 1, 1 ) ) )

    def test_none_for_a_same_year_figure( self ):
        self.assertIsNone(
            to_todays_dollars( _run( 2026, Decimal( '0.03' ) ), Decimal( '100' ), date( 2026, 12, 31 ) ) )

    def test_none_for_a_figure_before_the_start_year( self ):
        self.assertIsNone(
            to_todays_dollars( _run( 2026, Decimal( '0.03' ) ), Decimal( '100' ), date( 2025, 12, 31 ) ) )

    def test_none_without_an_assumptions_set( self ):
        self.assertIsNone(
            to_todays_dollars( _run( 2026, has_assumptions = False ), Decimal( '100' ), date( 2036, 1, 1 ) ) )


class DeflationFactorTests( unittest.TestCase ):

    def test_identity_when_there_is_nothing_to_discount( self ):
        self.assertEqual( deflation_factor( _run( 2026, Decimal( '0' ) ), date( 2036, 1, 1 ) ), Decimal( '1' ) )
        self.assertEqual(                                                             # same-year figure
            deflation_factor( _run( 2026, Decimal( '0.03' ) ), date( 2026, 6, 1 ) ), Decimal( '1' ) )

    def test_factor_restates_a_later_figure_in_start_year_dollars( self ):
        factor = deflation_factor( _run( 2026, Decimal( '0.05' ) ), date( 2029, 1, 1 ) )   # 3 whole years
        self.assertEqual( factor, Decimal( '1' ) / ( Decimal( '1.05' ) ** 3 ) )
        self.assertLess( factor, Decimal( '1' ) )
