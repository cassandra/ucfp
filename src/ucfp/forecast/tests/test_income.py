"""Tests for income resolution in a Forecast (no DB -- the engine is pure domain).

Covers the foundational wiring: per-person income accounts and the today's-dollars ->
nominal COLA growth from the forecast start. Revenue accounts only receive income, so the
assertions are robust to whatever tax/funding posts elsewhere.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.rate import FULL_RATE, ZERO_RATE, Rate
from common.recurrence import Duration, OneTime, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    IncomeItem,
    IncomeStream,
    Subject,
    WindowedAmount,
)
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection


def _run_two_pension_forecast():
    """Two people with Social Security, a 2% SS COLA, over 2026-2028."""
    alice = Subject( 'Alice', date( 1958, 1, 1 ), 'alice' )
    bob = Subject( 'Bob', date( 1960, 1, 1 ), 'bob' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2028, 12, 31 ),
        filing_status = FilingStatus.MARRIED_JOINT,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ alice, bob ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '10000' ), Decimal( '10000' ) ) ],
        economic_outlook = EconomicOutlook.constant(
            EconomicParameters( social_security_cola = Rate( Decimal( '0.02' ) ) ) ),
        income_streams = [
            IncomeStream( alice, IncomeTaxClass.SOCIAL_SECURITY,
                          Schedule.constant( WindowedAmount( Decimal( '30000' ) ) ) ),
            IncomeStream( bob, IncomeTaxClass.SOCIAL_SECURITY,
                          Schedule.constant( WindowedAmount( Decimal( '20000' ) ) ) ),
        ],
    )
    return Forecast( parameters ).run()


def _run_ss_reduction_forecast( benefits_payable, reduction_year, cola = ZERO_RATE ):
    """One person's Social Security ($30k) and pension ($10k) over 2026-2029, with the funding
    reduction to `benefits_payable` from `reduction_year` (and an optional SS COLA) -- exercises the
    engine-side benefit-payable factor, and that it touches Social Security only (not the pension)."""
    alice = Subject( 'Alice', date( 1958, 1, 1 ), 'alice' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2029, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ alice ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '10000' ), Decimal( '10000' ) ) ],
        economic_outlook = EconomicOutlook.constant( EconomicParameters(
            social_security_cola = cola,
            social_security_benefits_payable = benefits_payable,
            social_security_reduction_year = reduction_year ) ),
        income_streams = [
            IncomeStream( alice, IncomeTaxClass.SOCIAL_SECURITY,
                          Schedule.constant( WindowedAmount( Decimal( '30000' ) ) ) ),
            IncomeStream( alice, IncomeTaxClass.PENSION,
                          Schedule.constant( WindowedAmount( Decimal( '10000' ) ) ) ),
        ],
    )
    return Forecast( parameters ).run()


def _run_stepped_wage_forecast():
    """A single earner whose wages step down from 100k to 50k in 2028 (no economic growth),
    over 2026-2029 -- exercises a stepped stream Schedule, where the amount changes at a
    segment boundary rather than via a rate."""
    worker = Subject( 'Worker', date( 1980, 1, 1 ), 'worker' )
    wages = Schedule( (
        WindowedAmount( Decimal( '100000' ), DateWindow( end = date( 2027, 12, 31 ) ) ),
        WindowedAmount( Decimal( '50000' ), DateWindow( start = date( 2028, 1, 1 ) ) ),
    ) )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2029, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ worker ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ) ],
        income_streams = [ IncomeStream( worker, IncomeTaxClass.WAGES, wages ) ],
    )
    return Forecast( parameters ).run()


def _run_recurring_income_forecast():
    """$5,000/month consulting income (a monthly Recurrence), no growth, over 2026-2027. The
    engine resolves count x amount (12 a year), so the income is stated at its natural
    per-occurrence figure rather than pre-annualized."""
    worker = Subject( 'Worker', date( 1980, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2027, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ worker ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ) ) ],
        income_items  = [ IncomeItem(
            worker, IncomeTaxClass.ORDINARY, Schedule.constant( WindowedAmount( Decimal( '5000' ) ) ),
            Recurrence( Duration( 1, TimeUnit.MONTH ) ) ) ],
    )
    return Forecast( parameters ).run()


def _run_one_time_income_forecast():
    """A single $50,000 receipt in 2028 (a OneTime), no growth, over 2026-2029 -- a one-time
    income posts once, in the year of its date, and not otherwise."""
    worker = Subject( 'Worker', date( 1980, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2029, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ worker ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '100000' ), Decimal( '100000' ) ) ],
        income_items  = [ IncomeItem(
            worker, IncomeTaxClass.ORDINARY, Schedule.constant( WindowedAmount( Decimal( '50000' ) ) ),
            OneTime( date( 2028, 6, 1 ) ) ) ],
    )
    return Forecast( parameters ).run()


def _run_income_class_forecast( income_tax_class ):
    """A single retiree with $40,000/yr of income of `income_tax_class`, full-year 2026, current law --
    used to compare how a class is booked and taxed (e.g. PENSION vs generic ORDINARY)."""
    person = Subject( 'Ret', date( 1950, 1, 1 ), 'ret' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2026, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ person ],
        assets        = [ AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ) ],
        income_streams = [ IncomeStream(
            person, income_tax_class, Schedule.constant( WindowedAmount( Decimal( '40000' ) ) ) ) ],
    )
    return Forecast( parameters ).run()


def _run_two_named_wage_flows():
    """One earner with two named WAGES flows (two jobs), full-year 2026 -- they share the single
    (worker, WAGES) account, so only the posting memo tells them apart."""
    worker = Subject( 'Worker', date( 1980, 1, 1 ), 'worker' )
    parameters = ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2026, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute  = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects      = [ worker ],
        assets        = [ AssetParameters( 'Cash', AssetClass.CASH, Decimal( '10000' ), Decimal( '10000' ) ) ],
        income_streams = [
            IncomeStream( worker, IncomeTaxClass.WAGES,
                          Schedule.constant( WindowedAmount( Decimal( '80000' ) ) ), name = 'Day job' ),
            IncomeStream( worker, IncomeTaxClass.WAGES,
                          Schedule.constant( WindowedAmount( Decimal( '20000' ) ) ), name = 'Consulting' ) ],
    )
    return Forecast( parameters ).run()


class IncomeForecastTests( unittest.TestCase ):

    def test_collapsed_wage_flows_are_told_apart_by_the_posting_memo( self ):
        # Two WAGES flows for one worker share a single revenue account, so the memo is the only thing
        # that distinguishes their postings in the drill-down.
        reader   = Bookkeeper( _run_two_named_wage_flows().books )
        wages    = reader.chart.income_account( IncomeTaxClass.WAGES, owner_handle = 'worker' )
        credited = { txn.description: entry.account
                     for txn in reader.books.transactions
                     for entry in txn.entries if entry.account is wages }
        self.assertEqual( set( credited ), { 'Day job', 'Consulting' } )   # both post, each with its label
        self.assertEqual( list( credited.values() ), [ wages, wages ] )    # into the one shared account

    def test_recurring_income_item_resolves_count_times_amount( self ):
        result = _run_recurring_income_forecast()
        reader = Bookkeeper( result.books )
        ordinary = reader.chart.income_account( IncomeTaxClass.ORDINARY, owner_handle = 'worker' )
        # $5,000 x 12 months = $60,000 a year, no growth -- never pre-annualized by the caller
        self.assertEqual(
            reader.ledger.natural_balance( ordinary, through = date( 2026, 12, 31 ) ), Decimal( '60000' ) )
        self.assertEqual(
            reader.ledger.natural_balance( ordinary, through = date( 2027, 12, 31 ) ), Decimal( '120000' ) )

    def test_pension_books_its_own_account_and_taxes_like_ordinary_income( self ):
        # Pension income is its own class (so a state exemption can target it), but folds into ordinary
        # income for federal tax -- identical result to the same amount of generic ordinary income.
        pension  = Bookkeeper( _run_income_class_forecast( IncomeTaxClass.PENSION ).books )
        ordinary = Bookkeeper( _run_income_class_forecast( IncomeTaxClass.ORDINARY ).books )
        through  = date( 2026, 12, 31 )
        pension_accounts  = [ a for a in pension.chart.accounts()
                              if a.income_tax_class == IncomeTaxClass.PENSION ]
        ordinary_accounts = [ a for a in pension.chart.accounts()
                              if a.income_tax_class == IncomeTaxClass.ORDINARY ]
        self.assertEqual( len( pension_accounts ), 1 )                       # pension has its own account
        self.assertEqual(
            pension.ledger.natural_balance( pension_accounts[ 0 ], through = through ), Decimal( '40000' ) )
        self.assertEqual( ordinary_accounts, [] )                           # not booked as generic ordinary
        self.assertEqual(                                                    # taxed exactly as ordinary income
            pension.ledger.net_worth( through = through ),
            ordinary.ledger.net_worth( through = through ) )

    def test_one_time_income_item_posts_once_in_its_year( self ):
        result = _run_one_time_income_forecast()
        reader = Bookkeeper( result.books )
        ordinary = reader.chart.income_account( IncomeTaxClass.ORDINARY, owner_handle = 'worker' )
        ledger = reader.ledger
        # nothing before the event year, the full amount in it, nothing after
        self.assertEqual( ledger.natural_balance( ordinary, through = date( 2027, 12, 31 ) ), Decimal( '0' ) )
        self.assertEqual( ledger.natural_balance( ordinary, through = date( 2028, 12, 31 ) ), Decimal( '50000' ) )
        self.assertEqual( ledger.natural_balance( ordinary, through = date( 2029, 12, 31 ) ), Decimal( '50000' ) )

    def test_stepped_stream_amount_changes_at_its_segment_boundary( self ):
        result = _run_stepped_wage_forecast()
        reader = Bookkeeper( result.books )
        wages = reader.chart.income_account( IncomeTaxClass.WAGES, owner_handle = 'worker' )
        ledger = reader.ledger
        # 100k in 2026 and 2027, then 50k in 2028 and 2029 -- the cumulative WAGES total steps
        self.assertEqual(
            ledger.natural_balance( wages, through = date( 2026, 12, 31 ) ), Decimal( '100000' ) )
        self.assertEqual(
            ledger.natural_balance( wages, through = date( 2027, 12, 31 ) ), Decimal( '200000' ) )
        self.assertEqual(
            ledger.natural_balance( wages, through = date( 2028, 12, 31 ) ), Decimal( '250000' ) )
        self.assertEqual(
            ledger.natural_balance( wages, through = date( 2029, 12, 31 ) ), Decimal( '300000' ) )

    def test_social_security_is_per_person( self ):
        result = _run_two_pension_forecast()
        chart = Bookkeeper( result.books ).chart
        # a distinct Social Security account per subject, found by owner handle
        alice_ss = chart.income_account( IncomeTaxClass.SOCIAL_SECURITY, owner_handle = 'alice' )
        bob_ss = chart.income_account( IncomeTaxClass.SOCIAL_SECURITY, owner_handle = 'bob' )
        self.assertIsNotNone( alice_ss )
        self.assertIsNotNone( bob_ss )
        self.assertIsNot( alice_ss, bob_ss )

    def test_income_grows_by_cola_from_forecast_start( self ):
        result = _run_two_pension_forecast()
        reader = Bookkeeper( result.books )
        alice_ss = reader.chart.income_account(
            IncomeTaxClass.SOCIAL_SECURITY, owner_handle = 'alice' )
        # start year is the base (no growth); then +2% a year, accumulating in the account
        self.assertEqual(
            reader.ledger.natural_balance( alice_ss, through = date( 2026, 12, 31 ) ), Decimal( '30000' ) )
        # 30000 + 30000*1.02 + 30000*1.02^2 = 30000 + 30600 + 31212
        self.assertEqual(
            reader.ledger.natural_balance( alice_ss, through = date( 2028, 12, 31 ) ), Decimal( '91812' ) )


class SocialSecurityReductionTests( unittest.TestCase ):
    """The funding-shortfall reduction, applied engine-side as a per-period benefit-payable factor."""

    def _balance( self, result, income_tax_class, through ):
        reader  = Bookkeeper( result.books )
        account = reader.chart.income_account( income_tax_class, owner_handle = 'alice' )
        return reader.ledger.natural_balance( account, through = through )

    def test_benefits_are_full_before_and_reduced_from_the_reduction_year( self ):
        result = _run_ss_reduction_forecast( Rate.percent( Decimal( '75' ) ), 2028 )   # 75% from 2028, no COLA
        self.assertEqual(                                                              # 2026 + 2027 full
            self._balance( result, IncomeTaxClass.SOCIAL_SECURITY, date( 2027, 12, 31 ) ), Decimal( '60000' ) )
        self.assertEqual(                                                              # + 2028 + 2029 at 75%
            self._balance( result, IncomeTaxClass.SOCIAL_SECURITY, date( 2029, 12, 31 ) ), Decimal( '105000' ) )

    def test_full_benefits_payable_is_a_noop( self ):
        result = _run_ss_reduction_forecast( FULL_RATE, 2028 )
        self.assertEqual(
            self._balance( result, IncomeTaxClass.SOCIAL_SECURITY, date( 2029, 12, 31 ) ), Decimal( '120000' ) )

    def test_the_reduction_leaves_a_pension_untouched( self ):
        result = _run_ss_reduction_forecast( Rate.percent( Decimal( '75' ) ), 2028 )
        self.assertEqual(                                                              # pension: 4 x 10000, unreduced
            self._balance( result, IncomeTaxClass.PENSION, date( 2029, 12, 31 ) ), Decimal( '40000' ) )

    def test_the_reduction_composes_multiplicatively_with_cola( self ):
        # 2% SS COLA and 75% payable from 2028. Nominal SS: 2026 30000, 2027 30600, 2028 31212*0.75=23409,
        # 2029 31836.24*0.75=23877.18. Cumulative through 2029 = 60600 + 23409 + 23877.18.
        result = _run_ss_reduction_forecast(
            Rate.percent( Decimal( '75' ) ), 2028, cola = Rate( Decimal( '0.02' ) ) )
        self.assertEqual(
            self._balance( result, IncomeTaxClass.SOCIAL_SECURITY, date( 2027, 12, 31 ) ), Decimal( '60600' ) )
        self.assertEqual(
            self._balance( result, IncomeTaxClass.SOCIAL_SECURITY, date( 2029, 12, 31 ) ),
            Decimal( '60600' ) + Decimal( '23409' ) + Decimal( '23877.18' ) )


if __name__ == '__main__':
    unittest.main()
