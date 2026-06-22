"""Differential (metamorphic) harness for granularity invariance.

Runs one `ForecastParameters` at annual / quarterly / monthly and extracts a year-by-year
figure set so the three runs can be compared. The engine documents that the same parameters
run at any granularity, so a material divergence flags a lurking month-vs-year assumption.

This is a diagnostic helper, deliberately NOT prefixed `test_` so the runner does not collect
it. The committed invariance assertions live in `test_granularity_invariance.py`; this module
is the shared machinery they (and ad-hoc drill-down) build on. All runs start January 1 --
mid-year starts are a separate feature (issue #17).
"""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Optional

from common.recurrence import Duration, TimeUnit
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType
from ucfp.forecast.forecast import Forecast, ForecastResult
from ucfp.forecast.parameters import ForecastParameters

ANNUAL    = Duration( 1, TimeUnit.YEAR )
QUARTERLY = Duration( 3, TimeUnit.MONTH )
MONTHLY   = Duration( 1, TimeUnit.MONTH )

# Coarse -> fine, so the report reads naturally and a quarterly value between annual and
# monthly supports the monotonicity check.
GRANULARITIES = ( ( 'annual', ANNUAL ), ( 'quarterly', QUARTERLY ), ( 'monthly', MONTHLY ) )

_ZERO = Decimal( '0' )


@dataclass( frozen = True )
class YearFigures:
    """One calendar year's figures from a run, read at year-end (Dec 31, or the horizon end
    for the final year). `income` and `expense` are per-tax-class magnitudes (both positive)."""

    year      : int
    net_worth : Decimal
    cash      : Decimal
    income    : dict
    expense   : dict

    @property
    def total_income( self ) -> Decimal:
        return sum( self.income.values(), _ZERO )

    @property
    def total_tax( self ) -> Decimal:
        return sum(
            ( amount for klass, amount in self.expense.items() if klass.is_tax_payment ), _ZERO )

    @property
    def total_operating_expense( self ) -> Decimal:
        return sum(
            ( amount for klass, amount in self.expense.items() if not klass.is_tax_payment ), _ZERO )


@dataclass( frozen = True )
class Outcome:
    """A run's planning outcome: the year net worth first depletes (None = survives the
    horizon) and the net worth at the end of the run -- the figures the materiality bar uses."""

    depletion_year     : Optional[ int ]
    terminal_net_worth : Decimal


def run_at( params : ForecastParameters, granularity : Duration ) -> ForecastResult:
    """Run `params` at `granularity`, with everything else identical."""
    return Forecast( replace( params, granularity = granularity ) ).run()


def yearly_figures( result : ForecastResult, params : ForecastParameters ) -> list:
    """The per-calendar-year `YearFigures` for a run, read at each year-end. A year the run
    never reached (it stopped early) simply reads the carried books -- flat flows, the final
    net worth -- which keeps the comparison aligned across granularities."""
    bookkeeper = Bookkeeper( result.books )
    ledger     = bookkeeper.ledger
    chart      = bookkeeper.chart
    cash       = chart.cash_account()
    revenue    = chart.accounts( account_type = AccountType.REVENUE )
    expense    = chart.accounts( account_type = AccountType.EXPENSE )
    figures = list()
    for year in range( params.start_date.year, params.end_date.year + 1 ):
        opening = date( year, 1, 1 )
        closing = min( date( year, 12, 31 ), params.end_date )
        figures.append(
            YearFigures(
                year      = year,
                net_worth = ledger.net_worth( through = closing ),
                cash      = ledger.market_value( cash, through = closing ) if cash is not None else _ZERO,
                income    = _flows_by_class(
                    ledger, revenue, 'income_tax_class', Decimal( '1' ), opening, closing ),
                expense   = _flows_by_class(
                    ledger, expense, 'expense_tax_class', Decimal( '-1' ), opening, closing ),
            ) )
        continue
    return figures


def outcome( result : ForecastResult, params : ForecastParameters ) -> Outcome:
    """A run's planning outcome (depletion year, terminal net worth)."""
    terminal  = Bookkeeper( result.books ).ledger.net_worth( through = params.end_date )
    depletion = result.steps[ -1 ].span.end_date.year if ( result.stopped_early and result.steps ) else None
    return Outcome( depletion_year = depletion, terminal_net_worth = terminal )


def compare( params : ForecastParameters ) -> dict:
    """Run `params` at every granularity and return `{ name : ( [ YearFigures ], Outcome ) }`."""
    comparison = dict()
    for name, granularity in GRANULARITIES:
        result = run_at( params, granularity )
        comparison[ name ] = ( yearly_figures( result, params ), outcome( result, params ) )
        continue
    return comparison


def render( comparison : dict ) -> str:
    """A readable year-by-year report of the headline metrics across granularities, with the
    monthly-vs-annual relative difference, plus the outcome summary -- for drill-down."""
    by_year = { name : { figures.year : figures for figures in year_list }
                for name, ( year_list, _outcome ) in comparison.items() }
    header = ( f'{"year":>6}  {"metric":<16} {"annual":>15} {"quarterly":>15} '
               f'{"monthly":>15}  {"m-vs-a":>9}' )
    lines = [ header ]
    for year in sorted( by_year[ 'annual' ] ):
        for label, metric in _METRICS:
            annual    = _metric_for( by_year, 'annual', year, metric )
            quarterly = _metric_for( by_year, 'quarterly', year, metric )
            monthly   = _metric_for( by_year, 'monthly', year, metric )
            lines.append(
                f'{year:>6}  {label:<16} {_money( annual ):>15} {_money( quarterly ):>15} '
                f'{_money( monthly ):>15}  {_relative( monthly, annual ):>9}' )
            continue
        continue
    lines.append( '' )
    for name, ( _year_list, run_outcome ) in comparison.items():
        lines.append(
            f'  {name:<10} depletion={run_outcome.depletion_year}  '
            f'terminal_net_worth={_money( run_outcome.terminal_net_worth )}' )
        continue
    return '\n'.join( lines )


_METRICS = (
    ( 'net_worth', lambda figures : figures.net_worth ),
    ( 'cash', lambda figures : figures.cash ),
    ( 'income', lambda figures : figures.total_income ),
    ( 'operating_expense', lambda figures : figures.total_operating_expense ),
    ( 'tax', lambda figures : figures.total_tax ),
)


def _flows_by_class( ledger, accounts, class_attr : str, sign : Decimal,
                     start : date, end : date ) -> dict:
    """Per-tax-class flow totals over `[start, end]`, summed across the accounts of each class
    (so per-worker wages and per-item expenses roll up). `sign` flips expense debits positive."""
    totals = dict()
    for account in accounts:
        klass = getattr( account, class_attr )
        if klass is None:
            continue
        totals[ klass ] = totals.get( klass, _ZERO ) + sign * ledger.flows(
            account, start = start, end = end )
        continue
    return totals


def _metric_for( by_year : dict, name : str, year : int, metric ) -> Optional[ Decimal ]:
    figures = by_year[ name ].get( year )
    return None if figures is None else metric( figures )


def _money( value : Optional[ Decimal ] ) -> str:
    return '--' if value is None else f'{value:,.0f}'


def _relative( monthly : Optional[ Decimal ], annual : Optional[ Decimal ] ) -> str:
    if ( monthly is None ) or ( annual is None ):
        return '--'
    if annual == 0:
        return '0' if monthly == 0 else 'n/a'
    return f'{( monthly - annual ) / abs( annual ) * 100:+.2f}%'
