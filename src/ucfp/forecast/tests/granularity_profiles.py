"""Profiles and isolation tiers for the granularity differential harness (issue #16).

A small, feature-spanning set of `ForecastParameters` (not exhaustive) crossed with isolation
**tiers** that progressively enable the sources of legitimate annual-vs-monthly divergence, so
a diff at a low tier is a strong bug signal:

- ``null``    -- zero economic rates, no cash floor/ceiling: rate flows and year-end levels
                 should match to rounding, so a diff there is a strong bug signal. (Loan
                 amortization still splits interest/principal per period, so a profile with a
                 loan drifts slightly even here -- expected, not a bug.)
- ``growth``  -- real rates, still no funding/sweep: isolates compounding-on-flows drift.
- ``funding`` -- real rates + the profile's floor/draw waterfall (no sweep): isolates
                 draw-frequency drift.
- ``full``    -- the profile's complete cash policy (floor, ceiling, sweep).

Each profile carries its realistic cash policy; the tiers strip it back. All start January 1
(mid-year is issue #17). This is diagnostic data, not a `test_` module.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from common.date_window import DateWindow
from common.rate import Rate
from common.recurrence import Duration, OneTime, Recurrence, TimeUnit
from common.schedule import Schedule
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass, RealPropertyType
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.parameters import (
    AssetAllocation,
    AssetParameters,
    CashAccountParameters,
    ContributionSource,
    ExpenseItem,
    ExpenseStream,
    ForecastParameters,
    IncomeItem,
    IncomeStream,
    LoanParameters,
    PropertyAttributes,
    RetirementContribution,
    ScheduledExternalDisbursement,
    ScheduledExternalReceipt,
    ScheduledRealization,
    Subject,
    SubjectRemoval,
    SubsidizedHealthCoverage,
    WindowedAmount,
)
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile

D = Decimal
_TAX = StatuteProfile( JurisdictionType.US_FEDERAL, StatuteForecastType.CURRENT_LAW )
_START = date( 2026, 1, 1 )
_END = date( 2045, 12, 31 )

NULL_OUTLOOK = EconomicOutlook.constant( EconomicParameters() )
REAL_OUTLOOK = EconomicOutlook.constant( EconomicParameters(
    inflation                = Rate( D( '0.025' ) ),
    wage_growth              = Rate( D( '0.03' ) ),
    stock_appreciation       = Rate( D( '0.06' ) ),
    stock_dividend           = Rate( D( '0.015' ) ),
    bond_interest            = Rate( D( '0.04' ) ),
    savings_interest         = Rate( D( '0.02' ) ),
    real_estate_appreciation = Rate( D( '0.04' ) ),
    retirement_growth        = Rate( D( '0.06' ) ),
    pension_cola             = Rate( D( '0.02' ) ),
    social_security_cola     = Rate( D( '0.025' ) ),
    rental_increase          = Rate( D( '0.03' ) ),
) )


def _stream( name : str, expense_class : ExpenseTaxClass, annual : str ) -> ExpenseStream:
    """A smooth cost with no meaningful sub-annual schedule (living, an annual vacation) -- the
    Rate intent, prorated evenly, so it must match across granularities."""
    return ExpenseStream( name, expense_class, Schedule.constant( WindowedAmount( D( annual ) ) ) )


def _income( subject : Subject, income_class : IncomeTaxClass, annual : str ) -> IncomeStream:
    """A smooth income at a level annual amount (the common case) -- the rate counterpart of
    `_stream`."""
    return IncomeStream( subject, income_class, Schedule.constant( WindowedAmount( D( annual ) ) ) )


def _recurring(
        name : str, expense_class : ExpenseTaxClass, amount : str, interval : Duration ) -> ExpenseItem:
    """A cost with a real cadence (a yearly property-tax bill) -- the Occurrence intent, placed by
    its recurrence, so its year-total matches but its intra-year timing may shift with granularity."""
    return ExpenseItem(
        name, expense_class, Schedule.constant( WindowedAmount( D( amount ) ) ), Recurrence( interval ) )


def _base( **overrides ) -> ForecastParameters:
    defaults = dict( start_date = _START, end_date = _END, statute = _TAX )
    defaults.update( overrides )
    return ForecastParameters( **defaults )


# -- profiles ---------------------------------------------------------------------------

def wage_earner() -> ForecastParameters:
    """A mid-career single earner: wages, living costs, a 401(k) contribution, and a cash band
    that sweeps surplus into the brokerage. Exercises wages, contributions, growth, sweep."""
    avery = Subject( 'Avery', date( 1986, 1, 1 ), 'avery' )
    return _base(
        filing_status = FilingStatus.SINGLE,
        subjects = [ avery ],
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, D( '50000' ), D( '50000' ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, D( '100000' ), D( '100000' ), handle = 'brokerage' ),
            AssetParameters( '401k', AssetClass.PRETAX_RETIREMENT, D( '0' ), D( '0' ),
                             handle = '401k', owner_handle = 'avery' ) ],
        income_streams = [ _income( avery, IncomeTaxClass.WAGES, '120000' ) ],
        expense_streams = [
            _stream( 'Living', ExpenseTaxClass.LIVING, '70000' ),
            _stream( 'Vacation', ExpenseTaxClass.LIVING, '8000' ) ],
        expense_items = [
            _recurring( 'Property Tax', ExpenseTaxClass.SALT, '9000', Duration( 1, TimeUnit.YEAR ) ) ],
        contributions = [ RetirementContribution( '401k', D( '20000' ), ContributionSource.WAGE ) ],
        cash_account = CashAccountParameters(
            cash_floor = D( '20000' ), cash_ceiling = D( '60000' ),
            draw_order = [ AssetClass.STOCKS ],
            sweep_allocation = AssetAllocation( ( ( 'brokerage', D( '1' ) ), ) ) ) )


def retiree() -> ForecastParameters:
    """A retiree spending beyond income, drawing down a brokerage then an IRA (with RMDs).
    Exercises Social Security, pension, RMDs, the funding waterfall, and depletion."""
    riley = Subject( 'Riley', date( 1953, 1, 1 ), 'riley' )
    return _base(
        filing_status = FilingStatus.SINGLE,
        subjects = [ riley ],
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, D( '40000' ), D( '40000' ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, D( '300000' ), D( '200000' ), handle = 'brokerage' ),
            AssetParameters( 'IRA', AssetClass.PRETAX_RETIREMENT, D( '400000' ), D( '0' ),
                             handle = 'ira', owner_handle = 'riley' ) ],
        income_streams = [
            _income( riley, IncomeTaxClass.SOCIAL_SECURITY, '30000' ),
            _income( riley, IncomeTaxClass.ORDINARY, '25000' ) ],
        expense_streams = [ _stream( 'Living', ExpenseTaxClass.LIVING, '130000' ) ],
        cash_account = CashAccountParameters(
            cash_floor = D( '20000' ),
            draw_order = [ AssetClass.STOCKS, AssetClass.PRETAX_RETIREMENT ] ) )


def rental_owner() -> ForecastParameters:
    """A landlord with a mortgaged rental sold mid-horizon. Exercises gross rent, rental
    depreciation, §1250 recapture on sale, loan amortization, and wages."""
    quinn = Subject( 'Quinn', date( 1976, 1, 1 ), 'quinn' )
    return _base(
        filing_status = FilingStatus.SINGLE,
        subjects = [ quinn ],
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, D( '60000' ), D( '60000' ) ),
            AssetParameters( 'Rental', AssetClass.REAL_ESTATE_RENTAL, D( '400000' ), D( '400000' ),
                             handle = 'rental',
                             property_attributes = PropertyAttributes(
                                 acquisition_date = date( 2026, 1, 1 ),
                                 depreciable_basis = D( '300000' ),
                                 property_type = RealPropertyType.RESIDENTIAL ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, D( '80000' ), D( '80000' ), handle = 'brokerage' ) ],
        income_streams = [
            _income( quinn, IncomeTaxClass.WAGES, '100000' ),
            _income( quinn, IncomeTaxClass.GROSS_RENTAL, '36000' ) ],
        expense_streams = [
            _stream( 'Living', ExpenseTaxClass.LIVING, '60000' ),
            _stream( 'Rental Expense', ExpenseTaxClass.RENTAL_EXPENSE, '12000' ) ],
        loans = [ LoanParameters(
            'Mortgage', D( '250000' ), Rate( D( '0.05' ) ), Duration( 30, TimeUnit.YEAR ),
            interest_class = ExpenseTaxClass.RENTAL_EXPENSE ) ],
        events = [ ScheduledRealization( date( 2040, 6, 1 ), 'rental', D( '800000' ) ) ],
        cash_account = CashAccountParameters(
            cash_floor = D( '20000' ), draw_order = [ AssetClass.STOCKS ] ) )


def couple_survivor() -> ForecastParameters:
    """A married couple where one spouse dies mid-horizon. Exercises the survivor transition
    (filing status, account retitling, household size), two earners' SS, RMDs, and draws."""
    sam = Subject( 'Sam', date( 1955, 1, 1 ), 'sam' )
    jordan = Subject( 'Jordan', date( 1957, 1, 1 ), 'jordan' )
    return _base(
        filing_status = FilingStatus.MARRIED_JOINT,
        subjects = [ sam, jordan ],
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, D( '60000' ), D( '60000' ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, D( '400000' ), D( '300000' ), handle = 'brokerage' ),
            AssetParameters( 'IRA-Sam', AssetClass.PRETAX_RETIREMENT, D( '300000' ), D( '0' ),
                             handle = 'ira-sam', owner_handle = 'sam' ),
            AssetParameters( 'IRA-Jordan', AssetClass.PRETAX_RETIREMENT, D( '200000' ), D( '0' ),
                             handle = 'ira-jordan', owner_handle = 'jordan' ) ],
        income_streams = [
            _income( sam, IncomeTaxClass.SOCIAL_SECURITY, '32000' ),
            _income( jordan, IncomeTaxClass.SOCIAL_SECURITY, '22000' ),
            _income( sam, IncomeTaxClass.ORDINARY, '20000' ) ],
        expense_streams = [ _stream( 'Living', ExpenseTaxClass.LIVING, '100000' ) ],
        subject_removals = [ SubjectRemoval( date( 2035, 6, 1 ), 'sam' ) ],
        cash_account = CashAccountParameters(
            cash_floor = D( '25000' ),
            draw_order = [ AssetClass.STOCKS, AssetClass.PRETAX_RETIREMENT ] ) )


def life_events() -> ForecastParameters:
    """An early retiree on subsidized health coverage who receives a non-taxable inheritance and a
    taxable one-time payment. Exercises the ACA premium tax credit (MAGI-sensitive), an external
    equity receipt, a one-time taxable income, sweep, and draws."""
    drew = Subject( 'Drew', date( 1964, 1, 1 ), 'drew' )
    return _base(
        filing_status = FilingStatus.SINGLE,
        subjects = [ drew ],
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, D( '50000' ), D( '50000' ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, D( '500000' ), D( '350000' ), handle = 'brokerage' ) ],
        income_streams = [ _income( drew, IncomeTaxClass.ORDINARY, '20000' ) ],
        income_items = [ IncomeItem(
            drew, IncomeTaxClass.ORDINARY, Schedule.constant( WindowedAmount( D( '50000' ) ) ),
            OneTime( date( 2032, 6, 1 ) ) ) ],
        expense_streams = [ _stream( 'Living', ExpenseTaxClass.LIVING, '70000' ) ],
        health_coverage = SubsidizedHealthCoverage( DateWindow( end = date( 2028, 12, 31 ) ), 1, D( '12000' ) ),
        events = [ ScheduledExternalReceipt( date( 2030, 6, 1 ), D( '100000' ) ) ],
        cash_account = CashAccountParameters(
            cash_floor = D( '20000' ), cash_ceiling = D( '80000' ),
            draw_order = [ AssetClass.STOCKS ],
            sweep_allocation = AssetAllocation( ( ( 'brokerage', D( '1' ) ), ) ) ) )


def gig_worker() -> ForecastParameters:
    """A self-employed earner paid per cadence: a monthly retainer (a recurring IncomeItem) and a
    year-end project bonus (a one-time IncomeItem), who makes a one-time family gift partway
    through. Exercises the occurrence-income shapes and the external-disbursement equity event."""
    sky = Subject( 'Sky', date( 1985, 1, 1 ), 'sky' )
    return _base(
        filing_status = FilingStatus.SINGLE,
        subjects = [ sky ],
        assets = [
            AssetParameters( 'Cash', AssetClass.CASH, D( '40000' ), D( '40000' ) ),
            AssetParameters( 'Brokerage', AssetClass.STOCKS, D( '150000' ), D( '120000' ), handle = 'brokerage' ) ],
        income_items = [
            IncomeItem( sky, IncomeTaxClass.ORDINARY, Schedule.constant( WindowedAmount( D( '5000' ) ) ),
                        Recurrence( Duration( 1, TimeUnit.MONTH ) ) ),
            IncomeItem( sky, IncomeTaxClass.ORDINARY, Schedule.constant( WindowedAmount( D( '30000' ) ) ),
                        OneTime( date( 2031, 12, 1 ) ) ) ],
        expense_streams = [ _stream( 'Living', ExpenseTaxClass.LIVING, '54000' ) ],
        events = [ ScheduledExternalDisbursement( date( 2035, 6, 1 ), D( '25000' ) ) ],
        cash_account = CashAccountParameters(
            cash_floor = D( '20000' ), cash_ceiling = D( '70000' ),
            draw_order = [ AssetClass.STOCKS ],
            sweep_allocation = AssetAllocation( ( ( 'brokerage', D( '1' ) ), ) ) ) )


PROFILES = {
    'wage_earner'     : wage_earner,
    'retiree'         : retiree,
    'rental_owner'    : rental_owner,
    'couple_survivor' : couple_survivor,
    'life_events'     : life_events,
    'gig_worker'      : gig_worker,
}


# -- isolation tiers --------------------------------------------------------------------

def null_tier( params : ForecastParameters ) -> ForecastParameters:
    return replace( params, economic_outlook = NULL_OUTLOOK, cash_account = CashAccountParameters() )


def growth_tier( params : ForecastParameters ) -> ForecastParameters:
    return replace( params, economic_outlook = REAL_OUTLOOK, cash_account = CashAccountParameters() )


def funding_tier( params : ForecastParameters ) -> ForecastParameters:
    funding_only = replace( params.cash_account, cash_ceiling = None, sweep_allocation = None )
    return replace( params, economic_outlook = REAL_OUTLOOK, cash_account = funding_only )


def full_tier( params : ForecastParameters ) -> ForecastParameters:
    return replace( params, economic_outlook = REAL_OUTLOOK )


TIERS = {
    'null'    : null_tier,
    'growth'  : growth_tier,
    'funding' : funding_tier,
    'full'    : full_tier,
}


# -- start dates ------------------------------------------------------------------------
# A second axis: the same profiles run from January 1 (a whole first year) and from a mid-year
# first-of-month (a partial first year, taxed by the section 443 estimate). Mid-year start
# interacts with the granularity machinery from a different angle (issue #17), so the differential
# is run over both.

_MID_START = date( 2026, 4, 1 )


def january_start( params : ForecastParameters ) -> ForecastParameters:
    return params


def mid_year_start( params : ForecastParameters ) -> ForecastParameters:
    return replace( params, start_date = _MID_START )


STARTS = {
    'january'  : january_start,
    'mid_year' : mid_year_start,
}


def matrix():
    """Yield ( profile_name, tier_name, start_name, params ) for every profile x tier x start
    combination -- the granularity differential is run over each."""
    for profile_name, build in PROFILES.items():
        base = build()
        for tier_name, tier in TIERS.items():
            for start_name, start in STARTS.items():
                yield ( profile_name, tier_name, start_name, start( tier( base ) ) )
                continue
            continue
        continue
