"""Unit tests for `AnnualizedFiscalWindow` -- the partial-year wrapper that grosses a fiscal window's
flows up to a full-year rate for the quarterly estimated-tax annualization (#172). The seam is easy to
invert (flows must scale by the factor; point-in-time facts must not), so it is pinned directly here
rather than only end-to-end through a forecast run."""
import unittest
from datetime import date
from decimal import Decimal

from common.date_span import DateSpan
from ucfp.period.fiscal_window import AnnualizedFiscalWindow


class _StubWindow:
    """A fake FiscalWindow exposing only what `AnnualizedFiscalWindow` reads: a span, the flows, and the
    point-in-time facts. Each returns a distinct constant so a mis-wired delegation is visible."""

    def __init__( self, span : DateSpan ):
        self._span = span

    @property
    def span( self ) -> DateSpan:
        return self._span

    def income( self, income_tax_class ) -> Decimal:
        return Decimal( '100' )

    def income_by_account( self, income_tax_class ) -> list[ Decimal ]:
        return [ Decimal( '60' ), Decimal( '40' ) ]

    def expense( self, expense_tax_class ) -> Decimal:
        return Decimal( '30' )

    def holdings( self ) -> list[ str ]:
        return [ 'holding-a', 'holding-b' ]

    def opening_value( self, holding ) -> Decimal:
        return Decimal( '500' )

    def distributions_to_cash( self, holding ) -> Decimal:
        return Decimal( '20' )

    def contributions_from_cash( self, holding ) -> Decimal:
        return Decimal( '10' )


_FULL_YEAR     = DateSpan( date( 2027, 1, 1 ), date( 2027, 12, 31 ) )
_FIRST_QUARTER = DateSpan( date( 2027, 1, 1 ), date( 2027, 3, 31 ) )   # 90 days in the non-leap year 2027


class AnnualizedFiscalWindowTests( unittest.TestCase ):

    def test_flows_scale_by_the_factor( self ):
        window = AnnualizedFiscalWindow( _StubWindow( _FULL_YEAR ), Decimal( '2' ) )
        self.assertEqual( window.income( None ), Decimal( '200' ) )
        self.assertEqual( window.income_by_account( None ), [ Decimal( '120' ), Decimal( '80' ) ] )
        self.assertEqual( window.expense( None ), Decimal( '60' ) )
        self.assertEqual( window.distributions_to_cash( None ), Decimal( '40' ) )
        self.assertEqual( window.contributions_from_cash( None ), Decimal( '20' ) )

    def test_point_in_time_facts_pass_through_unscaled( self ):
        window = AnnualizedFiscalWindow( _StubWindow( _FULL_YEAR ), Decimal( '2' ) )
        self.assertEqual( window.span, _FULL_YEAR )
        self.assertEqual( window.holdings(), [ 'holding-a', 'holding-b' ] )
        self.assertEqual( window.opening_value( 'holding-a' ), Decimal( '500' ) )   # the RMD base, not a flow

    def test_annualizing_a_full_year_is_a_no_op( self ):
        window = AnnualizedFiscalWindow.annualizing( _StubWindow( _FULL_YEAR ) )
        self.assertEqual( window.income( None ), Decimal( '100' ) )   # factor 365/365 == 1

    def test_annualizing_grosses_a_partial_year_up_to_a_full_year_rate( self ):
        window = AnnualizedFiscalWindow.annualizing( _StubWindow( _FIRST_QUARTER ) )
        factor = Decimal( 365 ) / Decimal( 90 )   # mirrors the class's own year-days / ytd-days
        self.assertEqual( window.income( None ), Decimal( '100' ) * factor )


if __name__ == '__main__':
    unittest.main()
