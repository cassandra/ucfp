"""End-to-end tests for rental real estate: the annual depreciation deduction and the
§1250 depreciation recapture at sale.

The depreciation *amounts* are exactly tested in ucfp.jurisdiction.us.tests.test_depreciation; here we
verify the integration through the Forecast: depreciation shields rental income while held,
and a sale recaptures it. The recapture's effect lands in the income-tax charge (bracket
math, not a book account), so it is verified directionally -- with vs. without an
accumulated-depreciation basis -- while the realize-side facts (the book gain into long-term
gains, the sale mechanics, a balanced ledger) are asserted exactly.

A rental's `cost_basis` is its ORIGINAL purchase price, not its depreciated/adjusted basis:
the book gain is proceeds - cost_basis (the appreciation, into long-term gains), and the
engine adds the depreciation back as §1250 recapture on top -- so passing the adjusted basis
would double-count the depreciation.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from common.recurrence import Duration, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    IncomeStream,
    LoanParameters,
    PropertyAttributes,
    ScheduledRealization,
    Subject,
    TransactionCosts,
    WindowedAmount,
)
from ucfp.forecast.tests.tax_helpers import total_income_tax
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.jurisdiction.us.depreciation import accumulated_depreciation
from ucfp.jurisdiction.us.state import PassiveLossCarryover, TaxState
from ucfp.period.results import NoticeKind


def _income_tax( reader ):
    return total_income_tax( reader )


class RentalDepreciationDeductionTests( unittest.TestCase ):
    """While a rental is held, depreciation reduces its taxable net income."""

    def _income_tax_with_basis( self, depreciable_basis ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'cash' ),
                AssetParameters(
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, Decimal( '500000' ), Decimal( '500000' ),
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = date( 2026, 1, 1 ),
                        depreciable_basis = depreciable_basis,
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            income_streams = [
                IncomeStream( subject, IncomeTaxClass.GROSS_RENTAL,
                              Schedule.constant( WindowedAmount( Decimal( '60000' ) ) ) ) ],
        )
        return _income_tax( Bookkeeper( Forecast( parameters ).run().books ) )

    def test_depreciation_lowers_tax_while_held( self ):
        # 275000 building basis depreciates 10000/yr, shielding that much rental income
        with_depreciation = self._income_tax_with_basis( Decimal( '275000' ) )
        without = self._income_tax_with_basis( Decimal( '0' ) )
        self.assertLess( with_depreciation, without )


class RentalLoanInterestNettingTests( unittest.TestCase ):
    """A rental mortgage's interest is a Schedule-E rental expense netted against gross rent, not
    itemized home-mortgage interest. Classed RENTAL_EXPENSE it nets dollar-for-dollar against the
    rental income; classed MORTGAGE_INTEREST (Schedule A) it gives a standard-deduction filer no
    benefit -- so the correct classification yields the lower tax."""

    def _income_tax_with_interest_class( self, interest_class ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        parameters = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'cash' ),
                AssetParameters(
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, Decimal( '500000' ), Decimal( '500000' ),
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = date( 2026, 1, 1 ),
                        depreciable_basis = Decimal( '0' ),               # isolate the interest effect
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            income_streams = [
                IncomeStream( subject, IncomeTaxClass.GROSS_RENTAL,
                              Schedule.constant( WindowedAmount( Decimal( '60000' ) ) ) ) ],
            loans = [ LoanParameters(
                'Rental Mortgage', Decimal( '250000' ), Rate( Decimal( '0.05' ) ),
                Duration( 30, TimeUnit.YEAR ), interest_class = interest_class ) ],
        )
        return _income_tax( Bookkeeper( Forecast( parameters ).run().books ) )

    def test_rental_loan_interest_nets_against_rent( self ):
        # The ~12,500 first-year interest nets against the 60k rent as a RENTAL_EXPENSE; as
        # itemized MORTGAGE_INTEREST it is below the single standard deduction, so it does not.
        netted     = self._income_tax_with_interest_class( ExpenseTaxClass.RENTAL_EXPENSE )
        itemizable = self._income_tax_with_interest_class( ExpenseTaxClass.MORTGAGE_INTEREST )
        self.assertLess( netted, itemizable )


class RentalSaleRecaptureTests( unittest.TestCase ):
    """Selling a rental: the appreciation is a long-term gain and the accumulated
    depreciation is recaptured (raising the tax)."""

    def _parameters( self, depreciable_basis ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        return ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters(
                    # market 600k now, bought for 400k in 2010 -> 200k appreciation embedded
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, Decimal( '600000' ), Decimal( '400000' ),
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = date( 2010, 1, 1 ),
                        depreciable_basis = depreciable_basis,
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            events        = [ ScheduledRealization( date( 2026, 1, 1 ), 'rental', Decimal( '600000' ) ) ],
        )

    def test_sale_mechanics_and_book_gain( self ):
        reader = Bookkeeper( Forecast( self._parameters( Decimal( '300000' ) ) ).run().books )
        ledger = reader.ledger
        through = date( 2026, 12, 31 )
        # the rental is emptied; its proceeds land in cash (less the year-end tax)
        self.assertEqual(
            ledger.market_value( reader.chart.account( 'rental' ), through = through ), Decimal( '0' ) )
        # the appreciation (600k - 400k basis) is recognized as the rental's own long-term sale gain
        rental_gain = reader.chart.income_account( IncomeTaxClass.RENTAL_SALE_GAIN )
        self.assertEqual( ledger.natural_balance( rental_gain ), Decimal( '200000' ) )
        reader.assert_balanced()

    def test_recapture_raises_tax_at_sale( self ):
        # identical sales except for the accumulated depreciation; the depreciated rental
        # recaptures it (a §1250 gain), so it owes more tax than the never-depreciated one
        depreciated = _income_tax(
            Bookkeeper( Forecast( self._parameters( Decimal( '300000' ) ) ).run().books ) )
        not_depreciated = _income_tax(
            Bookkeeper( Forecast( self._parameters( Decimal( '0' ) ) ).run().books ) )
        self.assertGreater( depreciated, not_depreciated )


class PropertySaleClosingCostsTests( unittest.TestCase ):
    """Selling a property charges closing costs -- a realtor fee on the sale price plus fixed costs --
    which reduce the recognized (taxable) gain and net proceeds, with a Notice. Non-real-estate sales
    are unaffected."""

    _REALTOR = Rate.percent( Decimal( 6 ) )
    _FIXED   = Decimal( '10000' )

    def _run( self, asset_class, costs, *, sale = date( 2026, 6, 1 ),
              end = date( 2026, 12, 31 ), outlook = None ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        return Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = end,
            filing_status = FilingStatus.SINGLE,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ subject ],
            economic_outlook = outlook if outlook is not None else EconomicOutlook(),
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters(
                    'Holding', asset_class, Decimal( '600000' ), Decimal( '400000' ), handle = 'sold',
                    owner_handle = 'subject-a' if asset_class is AssetClass.PRETAX_RETIREMENT else None,
                    property_attributes = ( PropertyAttributes(
                        acquisition_date = date( 2010, 1, 1 ), depreciable_basis = Decimal( '0' ),
                        property_type = RealPropertyType.RESIDENTIAL )
                        if asset_class is AssetClass.REAL_ESTATE_RENTAL else None ) ) ],
            events        = [ ScheduledRealization( sale, 'sold' ) ],   # full sale (no amount)
            property_sale_costs = costs ) ).run()

    def _costs( self ) -> TransactionCosts:
        return TransactionCosts(
            property_sale_realtor_fee_rate = self._REALTOR, property_sale_fixed_cost = self._FIXED )

    @staticmethod
    def _gain( run, income_class ) -> Decimal:
        reader = Bookkeeper( run.books )
        return reader.ledger.natural_balance( reader.chart.income_account( income_class ) )

    @staticmethod
    def _sale_cost_notices( run ) -> list:
        return [ n for step in run.steps for n in step.result.notices
                 if n.kind is NoticeKind.PROPERTY_SALE_COSTS ]

    def test_closing_costs_reduce_the_recognized_gain( self ):
        without = self._gain(
            self._run( AssetClass.REAL_ESTATE_RENTAL, TransactionCosts() ), IncomeTaxClass.RENTAL_SALE_GAIN )
        withc   = self._gain(
            self._run( AssetClass.REAL_ESTATE_RENTAL, self._costs() ), IncomeTaxClass.RENTAL_SALE_GAIN )
        # 6% of the 600k sale + 10k fixed = 46,000, taken off the rental sale gain
        self.assertEqual( without - withc, Decimal( '46000' ) )

    def test_a_notice_reports_the_total( self ):
        notices = self._sale_cost_notices( self._run( AssetClass.REAL_ESTATE_RENTAL, self._costs() ) )
        self.assertEqual( [ n.amount for n in notices ], [ Decimal( '46000' ) ] )

    def test_no_costs_no_charge( self ):
        self.assertEqual(
            self._sale_cost_notices( self._run( AssetClass.REAL_ESTATE_RENTAL, TransactionCosts() ) ), [] )

    def test_non_real_estate_sale_is_untouched( self ):
        # the same costs against a stock sale: no closing costs, no notice (they are property-only)
        self.assertEqual( self._sale_cost_notices( self._run( AssetClass.STOCKS, self._costs() ) ), [] )

    def test_residence_costs_hit_the_section_121_gain_and_inflate( self ):
        # A residence sold a year out, under 10% general inflation and no appreciation: the sale price
        # stays 600k, the 10k fixed cost inflates to 11k, so 6%*600k + 11k = 47,000 -- taken off the
        # residence (section 121) gain (not long-term gains), matching the notice, and reducing cash.
        outlook = EconomicOutlook.constant( EconomicParameters( inflation = Rate.percent( Decimal( 10 ) ) ) )
        later = dict( sale = date( 2027, 6, 1 ), end = date( 2027, 12, 31 ), outlook = outlook )
        without = self._gain(
            self._run( AssetClass.REAL_ESTATE_RESIDENCE, TransactionCosts(), **later ),
            IncomeTaxClass.RESIDENCE_SECTION_121_GAIN )
        run   = self._run( AssetClass.REAL_ESTATE_RESIDENCE, self._costs(), **later )
        withc = self._gain( run, IncomeTaxClass.RESIDENCE_SECTION_121_GAIN )
        self.assertEqual( without - withc, Decimal( '47000' ) )       # residence branch + fixed-cost inflation
        self.assertEqual( [ n.amount for n in self._sale_cost_notices( run ) ], [ Decimal( '47000' ) ] )
        # the linked cost-of-sale transaction credits (reduces) cash by the same total -- net proceeds fell
        reader = Bookkeeper( run.books )
        cash   = reader.chart.cash_account()
        txn    = next( t for t in run.books.transactions
                       if t.transaction_uuid == self._sale_cost_notices( run )[ 0 ].transaction_uuid )
        cash_credit = sum( ( e.signed_amount for e in txn.entries if e.account is cash ), Decimal( '0' ) )
        self.assertEqual( cash_credit, Decimal( '47000' ) )


class BelowCostSaleRecaptureCapTests( unittest.TestCase ):
    """A rental sold at its adjusted basis has zero total gain, so the §1250 cap recaptures nothing and
    the sale adds no tax -- exactly as if it were held. (Before the cap, the full accumulated
    depreciation was recaptured regardless of the sale price, over-taxing a below-cost sale.) The
    rental's market value is its adjusted basis, so a full sale books a loss equal to the accumulated
    depreciation, which the recapture exactly offsets to zero."""

    _COST  = Decimal( '400000' )   # original cost basis
    _BASIS = Decimal( '300000' )   # depreciable (building) portion
    _ACQ   = date( 2010, 1, 1 )
    _SALE  = date( 2026, 12, 31 )

    def _adjusted_basis( self ):
        recapture = accumulated_depreciation( self._BASIS, self._ACQ, self._SALE, RealPropertyType.RESIDENTIAL )
        return self._COST - recapture

    def _parameters( self, sell ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        events  = [ ScheduledRealization( self._SALE, 'rental', None ) ] if sell else []   # a full sale
        return ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters(
                    # market value == adjusted basis, original cost 400k: a full sale books a loss of
                    # the accumulated depreciation, which the §1250 recapture exactly offsets to zero.
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, self._adjusted_basis(), self._COST,
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = self._ACQ,
                        depreciable_basis = self._BASIS,
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            income_streams = [ IncomeStream(
                subject, IncomeTaxClass.ORDINARY,
                Schedule.constant( WindowedAmount( Decimal( '80000' ) ) ) ) ],
            events        = events,
        )

    def test_sale_at_adjusted_basis_recaptures_nothing( self ):
        sold = _income_tax( Bookkeeper( Forecast( self._parameters( sell = True ) ).run().books ) )
        held = _income_tax( Bookkeeper( Forecast( self._parameters( sell = False ) ).run().books ) )
        self.assertEqual( sold, held )   # zero total gain -> no recapture, unlike the old full-accumulation


class SuspendedLossReleaseOnSaleTests( unittest.TestCase ):
    """End-to-end: a rental carrying suspended passive losses releases the whole balance in the year it
    is sold (deductible against income), lowering that year's tax; held, the losses stay suspended. The
    rental is sold at cost with no depreciation, so the sale itself adds no gain -- isolating the
    release. A 200k salary keeps MAGI above the phase-out, so nothing but the disposition frees them."""

    def _parameters( self, sell ):
        subject = Subject( 'A', date( 1958, 1, 1 ), 'subject-a' )
        events  = [ ScheduledRealization( date( 2026, 12, 1 ), 'rental', Decimal( '400000' ) ) ] if sell else []
        return ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters(
                    'Rental', AssetClass.REAL_ESTATE_RENTAL, Decimal( '400000' ), Decimal( '400000' ),
                    handle = 'rental',
                    property_attributes = PropertyAttributes(
                        acquisition_date  = date( 2010, 1, 1 ),
                        depreciable_basis = Decimal( '0' ),          # no depreciation -> no §1250 recapture
                        property_type     = RealPropertyType.RESIDENTIAL ) ) ],
            income_streams = [ IncomeStream(
                subject, IncomeTaxClass.ORDINARY,
                Schedule.constant( WindowedAmount( Decimal( '200000' ) ) ) ) ],
            events        = events,
            initial_tax_state = TaxState(
                passive_loss_carryover = PassiveLossCarryover( suspended = Decimal( '50000' ) ) ),
        )

    @staticmethod
    def _closing_suspended( run ):
        return run.steps[ -1 ].result.closing_tax_state.passive_loss_carryover.suspended

    def test_selling_releases_suspended_losses_and_lowers_tax( self ):
        sold_run = Forecast( self._parameters( sell = True ) ).run()
        held_run = Forecast( self._parameters( sell = False ) ).run()
        self.assertEqual( self._closing_suspended( sold_run ), Decimal( '0' ) )       # the sale releases it
        self.assertEqual( self._closing_suspended( held_run ), Decimal( '50000' ) )   # held, it stays
        self.assertLess(                                                              # and the release cuts tax
            _income_tax( Bookkeeper( sold_run.books ) ), _income_tax( Bookkeeper( held_run.books ) ) )


if __name__ == '__main__':
    unittest.main()
