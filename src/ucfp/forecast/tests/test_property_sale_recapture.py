"""Characterization + guard tests for rental §1250 depreciation-recapture across the property-sale
paths the application actually uses (issue #187).

The engine recaptures a rental's accumulated straight-line depreciation as a §1250 gain only when the
Forecast hands the tax engine a `PropertyDisposition` for the sale year -- and that disposition is
driven by `Forecast._sale_date_of`, which today matches *only* `ScheduledRealization` events. But a
real property sale is never a raw `ScheduledRealization`: a user-scheduled sale is a
`ScheduledPropertySale` (-> period `PropertySale` -> `_sell_property_whole`), and a funding-waterfall
liquidation is also `_sell_property_whole`. Neither is seen by `_sale_date_of`, so for the app-reachable
sale paths recapture is $0, the sale-year depreciation deduction is a full year (not prorated to the
sale date), and the "sold" rental keeps phantom-depreciating in later years.

The existing `test_rental.py::RentalSaleRecaptureTests` and `test_property_sales.py` sell via
`ScheduledRealization`, so they pass -- but that path is not reachable from the UI. These tests
therefore sell exclusively via `ScheduledPropertySale` and via the funding waterfall.

Tests 1-4 assert the CORRECT post-fix behavior and are EXPECTED TO FAIL until #187 is fixed
(current code: $0 recapture / phantom depreciation / full-year deduction). Tests 5-7 are GUARDS that
must PASS now and stay passing -- the held-rental annual deduction, and the §121 residence exclusion
and second-home LTCG, which are computed from the BOOKED gain and so work on every sale path.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    CashAccountParameters,
    ExpenseItem,
    ForecastParameters,
    IncomeStream,
    PropertyAttributes,
    ScheduledPropertySale,
    Subject,
    WindowedAmount,
)
from ucfp.forecast.tests.tax_helpers import income_tax_accounts, total_income_tax
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.jurisdiction.us.depreciation import accumulated_depreciation

# A non-senior single filer: young enough that the senior standard-deduction bonus (and its
# AGI phase-out) never enters, so a sale year's large capital gain cannot move the *ordinary*
# bracket the depreciation deduction is read through (test 4).
_SUBJECT = Subject( 'A', date( 1975, 1, 1 ), 'subject-a' )
_STATUTE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )

# A residential rental acquired ten years before the forecast start, with a real building basis
# (so a decade of accumulated depreciation exists to recapture) and 200k of embedded appreciation
# (so the total gain comfortably exceeds the recapture and none of the §1250 bucket is capped away).
_ACQUISITION       = date( 2016, 1, 1 )
_DEPRECIABLE_BASIS  = Decimal( '275000' )   # building portion -> 275000 / 27.5 = 10000/yr straight-line
_COST_BASIS         = Decimal( '400000' )   # ORIGINAL purchase price (not the adjusted/depreciated basis)
_MARKET_VALUE       = Decimal( '600000' )   # t0 market value -> 200000 embedded gain over cost
_RENTAL_INCOME      = Decimal( '60000' )    # gross rents, shielded by the 10000/yr depreciation while held

_CAP_RATE      = Decimal( '0.25' )          # the §1250 unrecaptured-gain maximum rate
_CAP_EPSILON   = Decimal( '1' )             # cents-rounding slack on the 25% ceiling
_FLOOR_FRACTION = Decimal( '0.20' )         # a clear positive floor below the 25% cap


def _rental_parameters( *, depreciable_basis, end_date, events = (), cash = Decimal( '100000' ),
                        expense_items = (), cash_account = None ):
    """A single-rental forecast: cash plus the residential rental above, a flat gross-rental income
    stream, and whatever sale trigger (a `ScheduledPropertySale` event, or a funding `cash_account`)
    the caller supplies. Mirrors the construction idioms in `test_rental.py`."""
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = end_date,
        filing_status = FilingStatus.SINGLE,
        statute       = _STATUTE,
        subjects      = [ _SUBJECT ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, cash, cash, handle = 'cash' ),
            AssetParameters(
                'Rental', AssetClass.REAL_ESTATE_RENTAL, _MARKET_VALUE, _COST_BASIS,
                handle = 'rental',
                property_attributes = PropertyAttributes(
                    acquisition_date  = _ACQUISITION,
                    depreciable_basis = depreciable_basis,
                    property_type     = RealPropertyType.RESIDENTIAL ) ) ],
        income_streams = [
            IncomeStream( _SUBJECT, IncomeTaxClass.GROSS_RENTAL,
                          Schedule.constant( WindowedAmount( _RENTAL_INCOME ) ) ) ],
        expense_items  = list( expense_items ),
        events         = list( events ),
        cash_account   = cash_account if cash_account is not None else CashAccountParameters(),
    )


def _section_1250_tax( reader ) -> Decimal:
    """The tax charged to the §1250 recapture rate layer over the whole run. A single rental recaptures
    in exactly one year (its sale year), so this cumulative balance is that year's §1250 tax."""
    return reader.ledger.natural_balance( reader.chart.expense_account( ExpenseTaxClass.SECTION_1250_TAX ) )


def _income_tax_through( reader, through ) -> Decimal:
    """Total income tax accrued through `through` -- the rate-layer accounts summed at a cutoff date.
    Tax is accrued at each tax-year's December 31 close, so differencing two year-ends isolates a
    single year's tax."""
    return sum( ( reader.ledger.natural_balance( account, through = through )
                  for account in income_tax_accounts( reader.chart ) ), Decimal( '0' ) )


def _income_tax_in_year( reader, year ) -> Decimal:
    """The income tax accrued for tax `year` alone (its year-end cumulative less the prior year-end's)."""
    return ( _income_tax_through( reader, date( year, 12, 31 ) )
             - _income_tax_through( reader, date( year - 1, 12, 31 ) ) )


def _ordinary_income_tax_in_year( reader, year ) -> Decimal:
    """The ordinary-bracket tax accrued for tax `year` alone. Net rental income is ordinary; the sale
    gain and §1250 recapture stack in their own layers above it, so this account reads the depreciation
    deduction's effect (via net rental) without the gain confounding it."""
    account = reader.chart.expense_account( ExpenseTaxClass.ORDINARY_INCOME_TAX )
    return ( reader.ledger.natural_balance( account, through = date( year, 12, 31 ) )
             - reader.ledger.natural_balance( account, through = date( year - 1, 12, 31 ) ) )


def _property_sale_date( run, handle ) -> date:
    """The date the whole property `handle` was sold, read from the periods' reported sales -- so a
    funding-triggered sale (whose date the waterfall, not the planner, chooses) can be pinned exactly."""
    for step in run.steps:
        for sold_handle, sale_date, _rent_after in step.result.property_sales:
            if sold_handle == str( handle ):
                return sale_date
    raise AssertionError( f'No whole-property sale of "{handle}" was reported by the run.' )


class ScheduledPropertySaleRecaptureTests( unittest.TestCase ):
    """Selling a rental through `ScheduledPropertySale` -- the event the planning layer actually emits.

    EXPECTED RED until #187: `_sale_date_of` ignores `ScheduledPropertySale`, so no disposition reaches
    the engine -- recapture is $0, the sale-year deduction is a full year, and the rental keeps
    depreciating after it is gone."""

    _SALE_DATE = date( 2027, 7, 1 )   # mid-year: a held year (2026) precedes it, prorating applies

    def _recapture_through_sale( self ) -> Decimal:
        return accumulated_depreciation(
            _DEPRECIABLE_BASIS, _ACQUISITION, self._SALE_DATE, RealPropertyType.RESIDENTIAL )

    def test_scheduled_sale_recaptures_section_1250( self ):
        # RED until #187. The depreciated rental, sold via ScheduledPropertySale, must recapture its
        # accumulated depreciation as a §1250 gain taxed at up to 25%. Currently the §1250 account is $0.
        reader = Bookkeeper( Forecast( _rental_parameters(
            depreciable_basis = _DEPRECIABLE_BASIS, end_date = date( 2027, 12, 31 ),
            events = [ ScheduledPropertySale( self._SALE_DATE, 'rental', rent_after = True ) ] ) ).run().books )
        section_1250_tax = _section_1250_tax( reader )
        recapture        = self._recapture_through_sale()
        # positive, and on the order of (accumulated depreciation through the sale date) x 25% -- the
        # bucket sits high in the stack here, so it hits the 25% cap rather than a lower ordinary rate
        self.assertGreater( section_1250_tax, Decimal( '0' ) )
        self.assertGreater( section_1250_tax, _FLOOR_FRACTION * recapture )
        self.assertLessEqual( section_1250_tax, _CAP_RATE * recapture + _CAP_EPSILON )

    def test_scheduled_sale_of_depreciated_rental_owes_more_total_tax( self ):
        # RED until #187. A robust cross-check mirroring test_rental: identical scheduled sales differing
        # only in the accumulated depreciation; recaptured depreciation (a decade's worth, at 25%) far
        # outweighs the couple of held years' ordinary-rate deduction, so the depreciated rental owes more.
        def total_tax( depreciable_basis ):
            return total_income_tax( Bookkeeper( Forecast( _rental_parameters(
                depreciable_basis = depreciable_basis, end_date = date( 2027, 12, 31 ),
                events = [ ScheduledPropertySale( self._SALE_DATE, 'rental', rent_after = True ) ] ) ).run().books ) )
        self.assertGreater( total_tax( _DEPRECIABLE_BASIS ), total_tax( Decimal( '0' ) ) )

    def test_no_depreciation_deduction_after_the_sale( self ):
        # RED until #187. Once sold in 2027, the rental must contribute NO depreciation deduction in
        # later years. With gross rent still flowing (an independent income stream), a post-sale year's
        # tax must match the identical never-depreciated rental -- i.e. the sold rental shields nothing.
        # Currently the phantom, still-"held" rental keeps depreciating, under-taxing 2028 and 2029.
        def reader_for( depreciable_basis ):
            return Bookkeeper( Forecast( _rental_parameters(
                depreciable_basis = depreciable_basis, end_date = date( 2029, 12, 31 ),
                events = [ ScheduledPropertySale( self._SALE_DATE, 'rental', rent_after = True ) ] ) ).run().books )
        depreciated    = reader_for( _DEPRECIABLE_BASIS )
        never_depreciated = reader_for( Decimal( '0' ) )
        for post_sale_year in ( 2028, 2029 ):
            self.assertEqual(
                _income_tax_in_year( depreciated, post_sale_year ),
                _income_tax_in_year( never_depreciated, post_sale_year ),
                f'phantom depreciation lowered {post_sale_year} tax after the sale' )

    def test_sale_year_deduction_is_prorated_to_the_sale_date( self ):
        # RED until #187. A mid-year (July 1) sale must take only a half-year of depreciation in the
        # sale year -- less than a full year's, but more than none. Read through the ordinary-bracket
        # tax on net rental (the gain stacks in its own layer): a prorated deduction shields LESS than a
        # full-year one (so the ordinary tax is HIGHER than the held case) yet still shields SOMETHING
        # (so it is LOWER than the zero-depreciation case). Currently the full-year deduction is taken,
        # so the sold case equals the held case rather than exceeding it.
        sale_year = 2027
        sold = Bookkeeper( Forecast( _rental_parameters(
            depreciable_basis = _DEPRECIABLE_BASIS, end_date = date( sale_year, 12, 31 ),
            events = [ ScheduledPropertySale( self._SALE_DATE, 'rental', rent_after = True ) ] ) ).run().books )
        held = Bookkeeper( Forecast( _rental_parameters(   # same rental, never sold -> a full year's deduction
            depreciable_basis = _DEPRECIABLE_BASIS, end_date = date( sale_year, 12, 31 ) ) ).run().books )
        no_depreciation = Bookkeeper( Forecast( _rental_parameters(   # never sold, no basis -> zero deduction
            depreciable_basis = Decimal( '0' ), end_date = date( sale_year, 12, 31 ) ) ).run().books )
        sold_ordinary = _ordinary_income_tax_in_year( sold, sale_year )
        # prorated < full year -> shields less -> ordinary tax strictly above the full-year (held) case
        self.assertGreater( sold_ordinary, _ordinary_income_tax_in_year( held, sale_year ) )
        # ...but still a real deduction -> ordinary tax strictly below the zero-depreciation case
        self.assertLess( sold_ordinary, _ordinary_income_tax_in_year( no_depreciation, sale_year ) )


class FundingTriggeredSaleRecaptureTests( unittest.TestCase ):
    """Selling a rental through the funding waterfall -- the same `_sell_property_whole` routine a
    scheduled sale uses, reached when a cash shortfall forces a liquidation.

    EXPECTED RED until #187: a funding sale carries no `ScheduledRealization`, so `_sale_date_of`
    finds no disposition and recapture is $0 -- and it must instead recapture identically to a
    scheduled sale of the same rental on the same date."""

    _BIG_EXPENSE = ExpenseItem(
        'Living', ExpenseTaxClass.LIVING,
        Schedule.constant( WindowedAmount( Decimal( '300000' ) ) ),
        Recurrence( Duration( 1, TimeUnit.YEAR ) ) )

    def test_funding_sale_recaptures_section_1250( self ):
        # RED until #187. The forced sale must recapture §1250 just as a scheduled sale would.
        funding_run  = Forecast( _funding_parameters( self._BIG_EXPENSE ) ).run()
        sale_date    = _property_sale_date( funding_run, 'rental' )
        reader       = Bookkeeper( funding_run.books )
        section_1250_tax = _section_1250_tax( reader )
        recapture    = accumulated_depreciation(
            _DEPRECIABLE_BASIS, _ACQUISITION, sale_date, RealPropertyType.RESIDENTIAL )
        self.assertGreater( section_1250_tax, Decimal( '0' ) )
        self.assertGreater( section_1250_tax, _FLOOR_FRACTION * recapture )
        self.assertLessEqual( section_1250_tax, _CAP_RATE * recapture + _CAP_EPSILON )

    def test_funding_sale_recaptures_like_a_scheduled_sale_on_the_same_date( self ):
        # RED until #187 (currently both are $0). The funding-triggered §1250 must equal a scheduled
        # sale of the same rental on the very date the waterfall chose -- one shared sale routine, so
        # one recapture. Living expenses are non-deductible, so the two scenarios' taxable income (and
        # thus the §1250 bracket stack) match, isolating the recapture itself.
        funding_run = Forecast( _funding_parameters( self._BIG_EXPENSE ) ).run()
        sale_date   = _property_sale_date( funding_run, 'rental' )
        funding_1250 = _section_1250_tax( Bookkeeper( funding_run.books ) )
        scheduled_1250 = _section_1250_tax( Bookkeeper( Forecast( _rental_parameters(
            depreciable_basis = _DEPRECIABLE_BASIS, end_date = date( 2026, 12, 31 ),
            events = [ ScheduledPropertySale( sale_date, 'rental', rent_after = True ) ] ) ).run().books ) )
        self.assertAlmostEqual( funding_1250, scheduled_1250, delta = _CAP_EPSILON )


class HeldRentalDepreciationGuardTests( unittest.TestCase ):
    """GUARD (must stay GREEN): while a rental is held (no sale), its annual depreciation shields rental
    income and lowers tax. This path is independent of the disposition bug -- it mirrors
    `test_rental.py::RentalDepreciationDeductionTests` and must keep passing."""

    def test_held_depreciation_lowers_tax( self ):
        def total_tax( depreciable_basis ):
            return total_income_tax( Bookkeeper( Forecast( _rental_parameters(
                depreciable_basis = depreciable_basis, end_date = date( 2026, 12, 31 ) ) ).run().books ) )
        # 275000 building basis depreciates 10000/yr, shielding that much of the 60000 rent
        self.assertLess( total_tax( _DEPRECIABLE_BASIS ), total_tax( Decimal( '0' ) ) )


class ResidenceAndSecondHomeGuardTests( unittest.TestCase ):
    """GUARDS (must stay GREEN): §121 (residence) and second-home LTCG are computed from the BOOKED gain
    account, not the disposition, so they work on every sale path -- including the real
    `ScheduledPropertySale` one, which the existing `test_property_sales.py` never exercises (it uses
    `ScheduledRealization`). These pin the correct behavior on the app-reachable path."""

    _SUBJECTS = [ Subject( 'A', date( 1958, 1, 1 ) ), Subject( 'B', date( 1959, 1, 1 ) ) ]

    def _sale_parameters( self, asset_class ):
        # Bought for 200k, worth 600k at t0 (a 400k embedded gain), no further appreciation -> sells at
        # 600k. A scheduled whole-property sale mid-2026, no closing costs.
        return ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            statute       = _STATUTE,
            subjects      = self._SUBJECTS,
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ),
                AssetParameters(
                    'Holding', asset_class, Decimal( '600000' ), Decimal( '200000' ), handle = 'holding' ) ],
            events        = [ ScheduledPropertySale( date( 2026, 7, 1 ), 'holding', rent_after = False ) ],
        )

    def test_residence_gain_excluded_via_scheduled_property_sale( self ):
        # A primary residence sold via the REAL path: the 400k gain lands in its §121 account and, under
        # the 500k MFJ cap, is wholly excluded -- no tax, so the 600k proceeds stay intact.
        reader = Bookkeeper( Forecast(
            self._sale_parameters( AssetClass.REAL_ESTATE_RESIDENCE ) ).run().books )
        residence_gain = reader.chart.income_account( IncomeTaxClass.RESIDENCE_SECTION_121_GAIN )
        self.assertEqual( reader.ledger.natural_balance( residence_gain ), Decimal( '400000' ) )
        self.assertEqual( reader.ledger.net_worth( through = date( 2026, 12, 31 ) ), Decimal( '600000' ) )

    def test_second_home_gain_taxed_with_no_exclusion_via_scheduled_property_sale( self ):
        # A second home sold via the REAL path: the 400k gain lands in its own account and -- with no
        # §121 exclusion -- is taxed as a long-term gain, so net worth ends materially below the 600k
        # proceeds (an exclusion would have left the full 600k).
        reader = Bookkeeper( Forecast(
            self._sale_parameters( AssetClass.REAL_ESTATE_SECOND_HOME ) ).run().books )
        second_home_gain = reader.chart.income_account( IncomeTaxClass.SECOND_HOME_GAIN )
        self.assertEqual( reader.ledger.natural_balance( second_home_gain ), Decimal( '400000' ) )
        self.assertLess( reader.ledger.net_worth( through = date( 2026, 12, 31 ) ), Decimal( '590000' ) )


def _funding_parameters( big_expense ):
    """A shortfall scenario: 5k cash, a 300k living expense, and the rental as the only draw source, so
    the funding waterfall must sell the whole rental (no sale event) to cover the gap."""
    return _rental_parameters(
        depreciable_basis = _DEPRECIABLE_BASIS, end_date = date( 2026, 12, 31 ),
        cash = Decimal( '5000' ), expense_items = [ big_expense ],
        cash_account = CashAccountParameters(
            cash_floor = Decimal( '10000' ), draw_order = [ AssetClass.REAL_ESTATE_RENTAL ] ) )


if __name__ == '__main__':
    unittest.main()
