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
from typing import Optional

from common.datetime_utils import age_on
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
from ucfp.accounts.books_table import (
    BooksColumnKey,
    BooksTableColumnCatalog,
    column_series,
)
from ucfp.accounts.enums import AccountType

from .books_table import run_period_spans
from .materialization import primary_birthdate
from .schemas import ProjectionRun

# Semantic series colours as chart-scoped CSS custom properties with hex fallbacks:
# the palette themes through CSS (defined in main.css) yet still renders standalone,
# and the renderer stays colour-agnostic. Hues are the validated categorical set,
# assigned to match the run table's column hues (violet net worth, blue asset, red
# liability, green income, gold expense). Income/Expense sit in the CVD floor
# band, so the flows chart carries a legend as the required secondary encoding.
_NET_WORTH_COLOR    = 'var(--chart-net-worth-color, #4a3aa7)'
_ASSETS_COLOR       = 'var(--chart-assets-color, #2a78d6)'
_LIABILITIES_COLOR  = 'var(--chart-liabilities-color, #e34948)'
_INCOME_COLOR       = 'var(--chart-income-color, #008300)'
_EXPENSES_COLOR     = 'var(--chart-expenses-color, #b8860b)'

_NET_WORTH_LABEL    = 'Net Worth'

# Per-column drill-in palette (column_chart). The rollup line is a fixed dark "total"
# colour, drawn on top (it is the sum, so it is the highest line); its children cycle
# the validated categorical hues, then repeat them dashed -- a second channel so up to
# seven children stay distinguishable without new hues.
_TOTAL_COLOR = 'var(--chart-total-color, #334155)'
_CAT_COLORS  = [
    'var(--chart-cat-1, #2a78d6)',   # blue
    'var(--chart-cat-2, #008300)',   # green
    'var(--chart-cat-3, #e34948)',   # red
    'var(--chart-cat-4, #4a3aa7)',   # violet
    'var(--chart-cat-5, #b8860b)',   # gold
]
_CHILD_DASH = '6 4'

# Chart-shaping constants: how many axis ticks the full chart aims for, and the most
# lines a per-column drill-in shows (rollup + children) before falling back to just the
# rollup.
_MAX_X_TICKS       = 6
_Y_TICK_COUNT      = 4
_MAX_COLUMN_LINES  = 8


def net_worth_chart( run : ProjectionRun, books : BooksOfAccount, *,
                     chrome : str = CHROME_SPARKLINE,
                     width : Optional[ float ] = None, height : Optional[ float ] = None ) -> LineChart:
    """A single net-worth line over the run's timeline (defaults to a sparkline)."""
    spans  = run_period_spans( run )
    ledger = Bookkeeper( books ).ledger
    series = [ LineChartSeries(
        values = [ float( ledger.net_worth( through = span.end_date )) for span in spans ],
        label  = _NET_WORTH_LABEL,
        color  = _NET_WORTH_COLOR ) ]
    return _chart( spans, series, chrome, run = run, width = width, height = height )


def balances_chart( run : ProjectionRun, books : BooksOfAccount, *,
                    chrome : str = CHROME_FULL,
                    width : Optional[ float ] = None, height : Optional[ float ] = None ) -> LineChart:
    """Net worth and its two components -- assets and liabilities -- over the run's
    timeline: end-of-period balances (stock) on a shared scale. Net worth is listed
    first so it paints on top where it coincides with assets (small liabilities)."""
    spans  = run_period_spans( run )
    ledger = Bookkeeper( books ).ledger

    def balance( account_type ):    # stock: end-of-period balance
        return [ float( ledger.type_total( account_type, through = span.end_date ))
                 for span in spans ]

    net_worth = [ float( ledger.net_worth( through = span.end_date )) for span in spans ]
    series = [
        LineChartSeries( net_worth, _NET_WORTH_LABEL, _NET_WORTH_COLOR ),
        LineChartSeries( balance( AccountType.ASSET ), 'Assets', _ASSETS_COLOR ),
        LineChartSeries( balance( AccountType.LIABILITY ), 'Liabilities', _LIABILITIES_COLOR ),
    ]
    return _chart( spans, series, chrome, run = run, width = width, height = height )


def flows_chart( run : ProjectionRun, books : BooksOfAccount, *,
                 chrome : str = CHROME_FULL,
                 width : Optional[ float ] = None, height : Optional[ float ] = None ) -> LineChart:
    """Income and expenses over the run's timeline: within-period flows (flow) on
    their own scale, kept separate from the balances, which are orders of magnitude
    larger and would otherwise crush these to the baseline."""
    spans  = run_period_spans( run )
    ledger = Bookkeeper( books ).ledger

    def flow( account_type ):       # flow: movement within the period
        return [ float( ledger.type_flow( account_type, start = span.start_date, end = span.end_date ))
                 for span in spans ]

    series = [
        LineChartSeries( flow( AccountType.REVENUE ), 'Income', _INCOME_COLOR ),
        LineChartSeries( flow( AccountType.EXPENSE ), 'Expenses', _EXPENSES_COLOR ),
    ]
    return _chart( spans, series, chrome, run = run, width = width, height = height )


def column_chart( run : ProjectionRun, books : BooksOfAccount, column_key : BooksColumnKey, *,
                  width : Optional[ float ] = None, height : Optional[ float ] = None ) -> LineChart:
    """A per-column drill-in: the column's value over time (the same figure the table cell
    shows) and, when it is a rollup, its immediate children beside it. Children that read
    zero across every period are dropped (they add nothing and the table hides them too),
    and if the rollup plus its non-zero children would exceed `_MAX_COLUMN_LINES`, only the
    rollup is drawn. A rollup left with a single non-zero child collapses to one line (the
    two would be identical), named "Parent > Child". The rollup is listed first so it paints
    on top.

    Raises ValueError if `column_key` is not a column of this run's books.
    """
    spans      = run_period_spans( run )
    bookkeeper = Bookkeeper( books )
    ledger     = bookkeeper.ledger
    chart      = bookkeeper.chart
    catalog    = BooksTableColumnCatalog.build( chart )

    column = catalog.get( column_key )
    if column is None:
        raise ValueError( f'No such column: {column_key}.' )

    def values_for( key ):
        return [ float( value ) for value in column_series( catalog, ledger, chart, spans, key ) ]

    parent_values = values_for( column_key )
    children = [ ( catalog.get( member_key ).label, values_for( member_key ) )
                 for member_key in catalog.member_keys( column_key ) ]
    children = [ ( label, values ) for label, values in children if any( values ) ]

    if len( children ) == 1:
        # A rollup with one non-zero child is identical to that child, so draw one line
        # and name it for both (unless they share a name, which would just repeat it).
        child_label = children[ 0 ][ 0 ]
        label = child_label if child_label == column.label else f'{column.label} > {child_label}'
        series = [ LineChartSeries( parent_values, label, _TOTAL_COLOR ) ]
    else:
        series = [ LineChartSeries( parent_values, column.label, _TOTAL_COLOR ) ]
        if children and ( 1 + len( children ) ) <= _MAX_COLUMN_LINES:
            for index, ( label, values ) in enumerate( children ):
                color, dash = _child_style( index )
                series.append( LineChartSeries( values, label, color, dash = dash ))

    return _chart( spans, series, CHROME_FULL, run = run, width = width, height = height )


def _child_style( index : int ):
    """The (colour, dash) for the nth child line: the categorical hues solid, then dashed."""
    color = _CAT_COLORS[ index % len( _CAT_COLORS ) ]
    dash  = _CHILD_DASH if index >= len( _CAT_COLORS ) else None
    return ( color, dash )


def _chart( spans : list, series : list[ LineChartSeries ], chrome : str, *,
            run : ProjectionRun = None,
            width : Optional[ float ] = None, height : Optional[ float ] = None ) -> LineChart:
    x    = [ _x_position( span.end_date ) for span in spans ]
    dims = {}
    if width is not None:
        dims[ 'width' ] = width
    if height is not None:
        dims[ 'height' ] = height
    if chrome != CHROME_FULL:
        # A sparkline shows the trajectory shape and fills its box (the surrounding
        # KPIs carry the absolute figures), so it scales to the data rather than
        # forcing a zero baseline. A crossing into negative still shows a zero line.
        return LineChart( x = x, series = series, chrome = chrome, include_zero = False, **dims )
    y_low, y_high, y_ticks = _y_axis( series )
    return LineChart(
        x        = x,
        series   = series,
        chrome   = chrome,
        x_ticks  = _x_ticks( spans, _primary_birthdate( run )),
        y_ticks  = y_ticks,
        y_min    = y_low,
        y_max    = y_high,
        **dims,
    )


def _primary_birthdate( run : ProjectionRun ):
    """The household's primary birthdate for age-labelling the x axis, or None."""
    profile = getattr( run, 'profile', None )
    return primary_birthdate( profile ) if profile is not None else None


def _x_position( on_date ) -> float:
    """A monotonic numeric x for a date -- its ordinal, so periods space by real time."""
    return float( on_date.toordinal() )


def _x_ticks( spans : list, birthdate = None ) -> list[ ChartTick ]:
    """Up to `_MAX_X_TICKS` year labels, evenly spaced across the period spans (deduped).

    When a primary `birthdate` is known, each label carries the primary subject's age
    that year as a parenthetical ("2040 (49)"), so the retirement-relevant years read
    without age math. The zero-length opening span is skipped for labelling -- its
    date is the prior year's close, so labelling it would put a stray year left of the
    forecast; the opening point is still plotted, just not ticked."""
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
        ticks.append( ChartTick( value = _x_position( end_date ), label = _x_label( end_date, birthdate )))
    return ticks


def _x_label( on_date, birthdate ) -> str:
    """A year label, with the primary subject's age that year in parentheses when known."""
    if birthdate is None:
        return str( on_date.year )
    return f'{on_date.year} ({age_on( birthdate, on_date )})'


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
