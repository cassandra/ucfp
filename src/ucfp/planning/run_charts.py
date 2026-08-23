"""Build line-chart specs from a captured run's books.

The domain adapter between a run's books of accounts and the generic
``common.line_chart`` renderer. It reads a run's timeline and per-period figures
off the ledger and owns the semantic series palette; the renderer itself stays
free of any domain or brand knowledge.

Two charts serve the app's surfaces:
  - `net_worth_chart` -- a single net-worth line (the dashboard / hub sparkline).
  - `run_books_chart` -- net worth plus the four account-type totals (the run
    output page's overview chart).

Series values are read live from the books (never cached; the books are the one
source of truth). Assets and liabilities are end-of-period balances (stock);
income and expenses are within-period flows -- so the opening span, being
zero-length, contributes a zero flow and the starting balances.
"""
from common.line_chart import (
    CHROME_FULL,
    CHROME_SPARKLINE,
    ChartTick,
    LineChart,
    LineChartSeries,
)
from common.math_utils import nice_ticks

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.books import BooksOfAccount
from ucfp.accounts.enums import AccountType

from .books_table import run_period_spans
from .schemas import ProjectionRun

# Semantic series colours as chart-scoped CSS custom properties with hex fallbacks:
# the palette themes through CSS (defined in main.css) yet still renders standalone,
# and the renderer stays colour-agnostic. Hues are the validated categorical set
# (see the data-viz palette); Assets/Expenses sit in the CVD floor band, so the
# run chart carries a legend as the required secondary encoding.
_NET_WORTH_COLOR    = 'var(--chart-net-worth-color, #2a78d6)'
_ASSETS_COLOR       = 'var(--chart-assets-color, #008300)'
_LIABILITIES_COLOR  = 'var(--chart-liabilities-color, #e34948)'
_INCOME_COLOR       = 'var(--chart-income-color, #4a3aa7)'
_EXPENSES_COLOR     = 'var(--chart-expenses-color, #eb6834)'

_NET_WORTH_LABEL    = 'Net Worth'

# Chart-shaping constants: how many axis ticks the full chart aims for.
_MAX_X_TICKS  = 6
_Y_TICK_COUNT = 4


def net_worth_chart( run : ProjectionRun, books : BooksOfAccount, *,
                     chrome : str = CHROME_SPARKLINE ) -> LineChart:
    """A single net-worth line over the run's timeline (defaults to a sparkline)."""
    spans  = run_period_spans( run )
    ledger = Bookkeeper( books ).ledger
    series = [ LineChartSeries(
        values = [ float( ledger.net_worth( through = span.end_date )) for span in spans ],
        label  = _NET_WORTH_LABEL,
        color  = _NET_WORTH_COLOR ) ]
    return _chart( spans, series, chrome )


def run_books_chart( run : ProjectionRun, books : BooksOfAccount, *,
                     chrome : str = CHROME_FULL ) -> LineChart:
    """Net worth plus the four account-type totals over the run's timeline."""
    spans  = run_period_spans( run )
    ledger = Bookkeeper( books ).ledger

    def net_worth():
        return [ float( ledger.net_worth( through = span.end_date )) for span in spans ]

    def balance( account_type ):    # stock: end-of-period balance
        return [ float( ledger.type_total( account_type, through = span.end_date ))
                 for span in spans ]

    def flow( account_type ):       # flow: movement within the period
        return [ float( ledger.type_flow( account_type, start = span.start_date, end = span.end_date ))
                 for span in spans ]

    series = [
        LineChartSeries( net_worth(), _NET_WORTH_LABEL, _NET_WORTH_COLOR ),
        LineChartSeries( balance( AccountType.ASSET ), 'Assets', _ASSETS_COLOR ),
        LineChartSeries( balance( AccountType.LIABILITY ), 'Liabilities', _LIABILITIES_COLOR ),
        LineChartSeries( flow( AccountType.REVENUE ), 'Income', _INCOME_COLOR ),
        LineChartSeries( flow( AccountType.EXPENSE ), 'Expenses', _EXPENSES_COLOR ),
    ]
    return _chart( spans, series, chrome )


def _chart( spans : list, series : list[ LineChartSeries ], chrome : str ) -> LineChart:
    x = [ _x_position( span.end_date ) for span in spans ]
    if chrome != CHROME_FULL:
        return LineChart( x = x, series = series, chrome = chrome )
    y_low, y_high, y_ticks = _y_axis( series )
    return LineChart(
        x        = x,
        series   = series,
        chrome   = chrome,
        x_ticks  = _x_ticks( spans ),
        y_ticks  = y_ticks,
        y_min    = y_low,
        y_max    = y_high,
    )


def _x_position( on_date ) -> float:
    """A monotonic numeric x for a date -- its ordinal, so periods space by real time."""
    return float( on_date.toordinal() )


def _x_ticks( spans : list ) -> list[ ChartTick ]:
    """Up to `_MAX_X_TICKS` year labels, evenly spaced across the period spans (deduped).

    The zero-length opening span is skipped for labelling -- its date is the prior
    year's close, so labelling it would put a stray year left of the forecast; the
    opening point is still plotted, just not ticked."""
    dated = [ span for span in spans if span.start_date != span.end_date ]
    if not dated:
        return []
    ticks = []
    seen  = set()
    for index in _even_indices( len( dated ), min( len( dated ), _MAX_X_TICKS )):
        end_date = dated[ index ].end_date
        if end_date.year in seen:
            continue
        seen.add( end_date.year )
        ticks.append( ChartTick( value = _x_position( end_date ), label = str( end_date.year )))
    return ticks


def _y_axis( series : list[ LineChartSeries ] ):
    """Nice, currency-labelled y ticks and the axis bounds snapped to them."""
    values = [ value for one in series for value in one.values ]
    if not values:
        return ( 0.0, 1.0, [] )
    tick_values = nice_ticks( min( 0.0, min( values )), max( 0.0, max( values )), _Y_TICK_COUNT )
    ticks = [ ChartTick( value = value, label = _format_money( value )) for value in tick_values ]
    return ( min( tick_values ), max( tick_values ), ticks )


def _even_indices( length : int, count : int ) -> list[ int ]:
    """`count` indices spread across range(length), including the first and last."""
    if count <= 1:
        return [ 0 ] if length else []
    step = ( length - 1 ) / ( count - 1 )
    return sorted( { round( step * position ) for position in range( count ) } )


def _format_money( value : float ) -> str:
    """A compact currency label: $0, -$50k, $1.2M."""
    magnitude = abs( value )
    sign      = '-' if value < 0 else ''
    if magnitude >= 1_000_000:
        return f'{sign}${magnitude / 1_000_000:g}M'
    if magnitude >= 1_000:
        return f'{sign}${magnitude / 1_000:g}k'
    return f'{sign}${magnitude:g}'
