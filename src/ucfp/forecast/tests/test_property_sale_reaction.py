"""The forecast's one-time reaction to a reported property sale (draw-order Phase 3b).

The per-period expense builders stay sale-agnostic; a reported sale reconfigures the working copy of the
expenses once -- ending the property's ownership costs, opening its dormant rent when the household rents
after, and ending the tenure-invariant utilities only when it does not. A sale of a property the forecast
has no `PropertyData` for reconfigures nothing. Whitebox on `_apply_property_sales`, the whole of that
reaction, so the generic builders need no residence awareness."""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.enums import ExpenseTaxClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import ExpenseItem, ForecastParameters, PropertyData, WindowedAmount
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection

_HANDLE = 'residence'
_SALE   = date( 2030, 6, 1 )


def _item( handle : str, window : DateWindow = DateWindow() ) -> ExpenseItem:
    return ExpenseItem(
        name = handle, expense_tax_class = ExpenseTaxClass.LIVING,
        amounts = Schedule( ( WindowedAmount( Decimal( '100' ), DateWindow() ), ) ),
        cadence = Recurrence( Duration( 1, TimeUnit.MONTH ) ), window = window, handle = handle )


def _forecast( items : list ) -> Forecast:
    forecast = Forecast( ForecastParameters(
        start_date    = date( 2026, 1, 1 ), end_date = date( 2036, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        expense_items = items,
        property_data = { _HANDLE: PropertyData(
            ownership_cost_handles = ( 'own', ), tenure_invariant_handles = ( 'util', ), rent_handle = 'rent' ) } ) )
    forecast._expense_items   = list( items )   # run() sets these; the reaction re-windows them
    forecast._expense_streams = list()
    return forecast


class PropertySaleReactionTests( unittest.TestCase ):

    def _react( self, rent_after : bool ) -> dict:
        forecast = _forecast( [ _item( 'own' ), _item( 'util' ), _item( 'rent', DateWindow( start = date.max ) ) ] )
        forecast._apply_property_sales( [ ( _HANDLE, _SALE, rent_after ) ] )
        return { item.handle: item for item in forecast._expense_items }

    def test_renting_after_ends_own_costs_keeps_utilities_opens_rent( self ):
        items = self._react( rent_after = True )
        self.assertEqual( items[ 'own' ].window.end, _SALE )       # ownership cost ends at the sale
        self.assertIsNone( items[ 'util' ].window.end )            # utility carries into the rental
        self.assertEqual( items[ 'rent' ].window.start, _SALE )    # rent opens from the sale

    def test_not_renting_after_ends_everything_and_leaves_rent_dormant( self ):
        items = self._react( rent_after = False )
        self.assertEqual( items[ 'own' ].window.end, _SALE )
        self.assertEqual( items[ 'util' ].window.end, _SALE )      # utility ends too -- no rental to carry into
        self.assertEqual( items[ 'rent' ].window.start, date.max )  # rent stays dormant

    def test_a_sale_with_no_property_data_reconfigures_nothing( self ):
        forecast = _forecast( [ _item( 'own' ) ] )
        forecast._apply_property_sales( [ ( 'unknown', _SALE, True ) ] )
        self.assertIsNone( forecast._expense_items[ 0 ].window.end )   # untouched


if __name__ == '__main__':
    unittest.main()
