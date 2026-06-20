"""Exact tests for the straight-line real-estate depreciation math (the §1250 core).

These pure functions are the computational heart of the rental deduction and §1250 recapture,
so they get exact/near-exact tests independent of the bracket machinery above them.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.enums import RealPropertyType
from ucfp.tax.us.depreciation import accumulated_depreciation, period_depreciation

_RESIDENTIAL = RealPropertyType.RESIDENTIAL


class AccumulatedDepreciationTests( unittest.TestCase ):

    def test_zero_before_acquisition( self ):
        accrued = accumulated_depreciation(
            Decimal( '275000' ), date( 2030, 1, 1 ), date( 2026, 1, 1 ), _RESIDENTIAL )
        self.assertEqual( accrued, Decimal( '0' ) )

    def test_zero_for_non_depreciable_basis( self ):
        # a personal residence (no building basis) never depreciates
        accrued = accumulated_depreciation(
            Decimal( '0' ), date( 2010, 1, 1 ), date( 2030, 1, 1 ), _RESIDENTIAL )
        self.assertEqual( accrued, Decimal( '0' ) )

    def test_capped_at_basis_once_fully_depreciated( self ):
        # past the 27.5-year recovery period the accumulation cannot exceed the basis
        accrued = accumulated_depreciation(
            Decimal( '100000' ), date( 2000, 1, 1 ), date( 2100, 1, 1 ), _RESIDENTIAL )
        self.assertEqual( accrued, Decimal( '100000' ) )

    def test_about_one_year_is_about_the_annual_amount( self ):
        # 27500 basis / 27.5 years = 1000/yr; one calendar year is ~that (365/365.25 days)
        accrued = accumulated_depreciation(
            Decimal( '27500' ), date( 2021, 1, 1 ), date( 2022, 1, 1 ), _RESIDENTIAL )
        self.assertAlmostEqual( accrued, Decimal( '1000' ), delta = Decimal( '2' ) )


class PeriodDepreciationTests( unittest.TestCase ):

    def test_window_is_additive( self ):
        # a window splits exactly: open->mid plus mid->close equals open->close
        basis, acquired = Decimal( '300000' ), date( 2015, 1, 1 )
        whole = period_depreciation(
            basis, acquired, _RESIDENTIAL, date( 2025, 12, 31 ), date( 2027, 12, 31 ) )
        first = period_depreciation(
            basis, acquired, _RESIDENTIAL, date( 2025, 12, 31 ), date( 2026, 12, 31 ) )
        second = period_depreciation(
            basis, acquired, _RESIDENTIAL, date( 2026, 12, 31 ), date( 2027, 12, 31 ) )
        self.assertEqual( whole, first + second )

    def test_window_is_the_accumulated_difference( self ):
        basis, acquired = Decimal( '300000' ), date( 2015, 1, 1 )
        opening = accumulated_depreciation( basis, acquired, date( 2025, 12, 31 ), _RESIDENTIAL )
        closing = accumulated_depreciation( basis, acquired, date( 2026, 12, 31 ), _RESIDENTIAL )
        window = period_depreciation(
            basis, acquired, _RESIDENTIAL, date( 2025, 12, 31 ), date( 2026, 12, 31 ) )
        self.assertEqual( window, closing - opening )


if __name__ == '__main__':
    unittest.main()
