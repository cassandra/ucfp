"""
Domain-agnostic multi-series line-chart geometry for server-side SVG rendering.

This module knows nothing about the application domain (accounts, runs, money) or
any brand palette. It takes a generic `LineChart` -- one shared numeric x axis and
one or more `LineChartSeries`, each with its own colour and label -- and computes
the pixel geometry (polylines, axes, gridlines, ticks, zero line, labels) needed to
draw it. The template ``charts/line_chart.svg`` turns that geometry into SVG, and
the ``{% line_chart %}`` tag (``common/templatetags/charts.py``) is the entry point.

Design notes:
  - Series colours arrive as explicit CSS colour values on each series (a hex
    string, ``currentColor``, or a ``var(--x)`` reference) -- the renderer never
    chooses a colour. Structural chrome (axes, gridlines, ticks, zero line) is
    coloured through chart-scoped CSS custom properties with fallbacks, so a theme
    layer can restyle it without touching this code.
  - Points are positioned by their real numeric x value, so variable-width periods
    render proportionally.
  - The y domain includes zero by default (net worth can go negative), and a zero
    line is drawn whenever zero falls strictly inside the domain.
  - Output carries a ``viewBox`` but no fixed width/height, so one markup scales
    from a thumbnail to a full-width chart under CSS control.
"""
from dataclasses import dataclass, field
from typing import Optional

from common.svg_models import SvgViewBox

# Chrome levels: how much non-data structure to draw. `full` shows axes, ticks,
# gridlines and labels; `sparkline` is data-only (for thumbnails).
CHROME_FULL       = 'full'
CHROME_SPARKLINE  = 'sparkline'
CHART_CHROME      = { CHROME_FULL, CHROME_SPARKLINE }

# Logical canvas size (user units). Only the aspect ratio and relative stroke/label
# sizes matter -- the rendered SVG has no fixed pixel size and scales via viewBox.
DEFAULT_WIDTH   = 320.0
DEFAULT_HEIGHT  = 180.0

DEFAULT_STROKE_WIDTH  = 2.0

# Text sizes in viewBox units. SVG <text> has no intrinsic size, so we set these
# explicitly; left implicit, the browser default (~16px) scales with the viewBox
# and renders far too large.
TICK_FONT_SIZE        = 9.0
AXIS_TITLE_FONT_SIZE  = 9.0

# Plot-area insets for `full` chrome (room for tick labels / axes), plus the extra
# room an axis title needs when present. Sized to the fonts above.
_MARGIN_FULL       = { 'left': 34.0, 'right': 10.0, 'top': 9.0, 'bottom': 16.0 }
_AXIS_LABEL_SPACE  = 12.0

# `sparkline` chrome pads just enough that a stroke at an extreme value is not
# clipped at the edge of the viewBox.
_SPARKLINE_PAD  = 4.0

# Number of intervals for auto-generated y ticks when the caller supplies none.
_AUTO_Y_TICK_INTERVALS  = 4

_EPSILON  = 1e-9


@dataclass
class LineChartSeries:
    """One line: a value per shared x position, with its own colour and label."""

    values  : list[ float ]
    label   : str
    color   : str            # any CSS colour value, incl. currentColor / var(--x)


@dataclass
class ChartTick:
    """An axis tick at a domain `value`, shown with the pre-formatted `label`.

    Labels are supplied ready-to-display so the renderer stays domain-agnostic --
    currency/date formatting is the caller's concern.
    """

    value  : float
    label  : str


@dataclass
class LineChart:
    """A multi-series line chart over one shared numeric x axis.

    All series share `x`; every series' `values` must be the same length as `x`.
    `x_ticks`/`y_ticks` are optional pre-formatted ticks (used only in `full`
    chrome); when omitted, `full` chrome auto-generates plain numeric ticks.
    """

    x             : list[ float ]
    series        : list[ LineChartSeries ]
    x_label       : Optional[ str ]              = None
    y_label       : Optional[ str ]              = None
    x_ticks       : Optional[ list[ ChartTick ]] = None
    y_ticks       : Optional[ list[ ChartTick ]] = None
    chrome        : str                          = CHROME_FULL
    include_zero  : bool                         = True
    y_min         : Optional[ float ]            = None   # override the data-derived y domain
    y_max         : Optional[ float ]            = None   # (e.g. to snap the axis to nice ticks)
    width         : float                        = DEFAULT_WIDTH
    height        : float                        = DEFAULT_HEIGHT
    stroke_width  : float                        = DEFAULT_STROKE_WIDTH


@dataclass
class RenderedSeries:
    points  : str            # SVG polyline "x1,y1 x2,y2 ..." in viewBox units
    color   : str
    label   : str


@dataclass
class RenderedTick:
    pos     : float          # pixel position along the relevant axis
    label   : str
    anchor  : str  = 'middle'   # SVG text-anchor (end for y; start/mid/end for x)


@dataclass
class RenderedText:
    x          : float
    y          : float
    text       : str
    transform  : str  = ''


@dataclass
class PlotArea:
    left    : float
    right   : float
    top     : float
    bottom  : float

    @property
    def inner_width(self):
        return self.right - self.left

    @property
    def inner_height(self):
        return self.bottom - self.top


@dataclass
class LineChartGeometry:
    """Everything the SVG template needs, in viewBox pixel units."""

    view_box         : SvgViewBox
    plot             : PlotArea
    series           : list[ RenderedSeries ]
    show_axes        : bool
    stroke_width     : float
    tick_font_size   : float  = TICK_FONT_SIZE
    axis_font_size   : float  = AXIS_TITLE_FONT_SIZE
    zero_line_y      : Optional[ float ]         = None
    gridlines        : list[ float ]             = field( default_factory = list )
    y_ticks          : list[ RenderedTick ]      = field( default_factory = list )
    x_ticks          : list[ RenderedTick ]      = field( default_factory = list )
    y_tick_label_x   : float                     = 0.0    # anchor x for y-tick labels
    x_tick_label_y   : float                     = 0.0    # anchor y for x-tick labels
    x_axis_label     : Optional[ RenderedText ]  = None
    y_axis_label     : Optional[ RenderedText ]  = None


def build_geometry( chart : LineChart ) -> LineChartGeometry:
    """Compute pixel geometry for `chart`. Pure -- no Django/template dependency."""
    _validate( chart )

    is_full   = ( chart.chrome == CHROME_FULL )
    view_box  = SvgViewBox( x = 0.0, y = 0.0, width = chart.width, height = chart.height )
    plot      = _plot_area( chart, is_full )

    x_min, x_max  = _x_domain( chart.x )
    y_min, y_max  = _y_domain( chart )

    def to_px_x( value ):
        return _scale( value, x_min, x_max, plot.left, plot.right )

    def to_px_y( value ):
        # SVG y grows downward: the domain minimum sits at the plot bottom.
        return _scale( value, y_min, y_max, plot.bottom, plot.top )

    rendered_series = [
        RenderedSeries(
            points  = _polyline_points( chart.x, series.values, to_px_x, to_px_y ),
            color   = series.color,
            label   = series.label,
        )
        for series in chart.series
    ]

    zero_line_y = to_px_y( 0.0 ) if ( y_min < 0.0 < y_max ) else None

    geometry = LineChartGeometry(
        view_box      = view_box,
        plot          = plot,
        series        = rendered_series,
        show_axes     = is_full,
        stroke_width  = chart.stroke_width,
        zero_line_y   = zero_line_y,
    )

    if is_full:
        _add_full_chrome( geometry, chart, y_min, y_max, to_px_x, to_px_y )

    return geometry


def _add_full_chrome( geometry, chart, y_min, y_max, to_px_x, to_px_y ):
    """Populate ticks, gridlines and axis labels for `full` chrome (in place)."""
    plot = geometry.plot

    y_ticks = chart.y_ticks if chart.y_ticks is not None else _auto_y_ticks( y_min, y_max )
    for tick in y_ticks:
        if ( tick.value < y_min - _EPSILON ) or ( tick.value > y_max + _EPSILON ):
            continue
        pos = to_px_y( tick.value )
        geometry.y_ticks.append( RenderedTick( pos = pos, label = tick.label, anchor = 'end' ))
        geometry.gridlines.append( pos )

    x_ticks = chart.x_ticks if chart.x_ticks is not None else _auto_x_ticks( chart.x )
    for tick in x_ticks:
        pos = to_px_x( tick.value )
        geometry.x_ticks.append(
            RenderedTick( pos = pos, label = tick.label, anchor = _x_tick_anchor( pos, plot )))

    # Tick labels sit just outside the plot: y labels a touch left of the axis,
    # x labels one font-height below it.
    geometry.y_tick_label_x  = plot.left   - 4.0
    geometry.x_tick_label_y  = plot.bottom + geometry.tick_font_size + 3.0

    if chart.x_label:
        geometry.x_axis_label = RenderedText(
            x     = ( plot.left + plot.right ) / 2.0,
            y     = geometry.view_box.max_y - 2.0,
            text  = chart.x_label,
        )
    if chart.y_label:
        title_x  = geometry.view_box.min_x + geometry.axis_font_size + 1.0
        center_y = ( plot.top + plot.bottom ) / 2.0
        geometry.y_axis_label = RenderedText(
            x          = title_x,
            y          = center_y,
            text       = chart.y_label,
            transform  = f'rotate( -90 {title_x} {center_y} )',
        )
    return


def _x_tick_anchor( pos : float, plot : PlotArea ) -> str:
    """Keep the first/last x labels inside the viewBox by anchoring them inward."""
    if pos <= plot.left + _EPSILON:
        return 'start'
    if pos >= plot.right - _EPSILON:
        return 'end'
    return 'middle'


def _plot_area( chart : LineChart, is_full : bool ) -> PlotArea:
    if not is_full:
        pad = _SPARKLINE_PAD + ( chart.stroke_width / 2.0 )
        return PlotArea(
            left    = pad,
            right   = chart.width  - pad,
            top     = pad,
            bottom  = chart.height - pad,
        )
    left    = _MARGIN_FULL['left']   + ( _AXIS_LABEL_SPACE if chart.y_label else 0.0 )
    bottom  = _MARGIN_FULL['bottom'] + ( _AXIS_LABEL_SPACE if chart.x_label else 0.0 )
    return PlotArea(
        left    = left,
        right   = chart.width  - _MARGIN_FULL['right'],
        top     = _MARGIN_FULL['top'],
        bottom  = chart.height - bottom,
    )


def _x_domain( x_values : list[ float ] ):
    if not x_values:
        return ( 0.0, 1.0 )
    x_min = min( x_values )
    x_max = max( x_values )
    if ( x_max - x_min ) < _EPSILON:
        # A single distinct x: give it a unit-wide domain so it lands mid-plot.
        return ( x_min - 0.5, x_min + 0.5 )
    return ( x_min, x_max )


def _y_domain( chart : LineChart ):
    bounds = _data_bounds( chart.series )
    if bounds is None:
        data_min, data_max = ( 0.0, 1.0 )
    else:
        data_min, data_max = bounds

    # An explicit override wins per end; otherwise derive from the data (folding in
    # zero when requested). The override still contains the data, so nothing clips.
    if chart.y_min is not None:
        y_min = chart.y_min
    else:
        y_min = min( 0.0, data_min ) if chart.include_zero else data_min
    if chart.y_max is not None:
        y_max = chart.y_max
    else:
        y_max = max( 0.0, data_max ) if chart.include_zero else data_max

    if ( y_max - y_min ) < _EPSILON:
        # Flat data (e.g. all zero): pad to a unit range so it draws as a line.
        return ( y_min - 1.0, y_max + 1.0 )
    return ( y_min, y_max )


def _data_bounds( series : list[ LineChartSeries ] ):
    values = [ value for one in series for value in one.values ]
    if not values:
        return None
    return ( min( values ), max( values ))


def _polyline_points( x_values, y_values, to_px_x, to_px_y ) -> str:
    points = [
        f'{_round( to_px_x( x ))},{_round( to_px_y( y ))}'
        for x, y in zip( x_values, y_values )
    ]
    return ' '.join( points )


def _auto_y_ticks( y_min : float, y_max : float ) -> list[ ChartTick ]:
    step  = ( y_max - y_min ) / _AUTO_Y_TICK_INTERVALS
    ticks = []
    for index in range( _AUTO_Y_TICK_INTERVALS + 1 ):
        value = y_min + ( step * index )
        ticks.append( ChartTick( value = value, label = _format_number( value )))
    return ticks


def _auto_x_ticks( x_values : list[ float ] ) -> list[ ChartTick ]:
    if not x_values:
        return []
    endpoints = { min( x_values ), max( x_values ) }
    return [ ChartTick( value = value, label = _format_number( value ))
             for value in sorted( endpoints ) ]


def _format_number( value : float ) -> str:
    rounded = round( value )
    if abs( value - rounded ) < _EPSILON:
        return str( int( rounded ))
    return f'{value:g}'


def _scale( value, domain_min, domain_max, pixel_min, pixel_max ) -> float:
    span = domain_max - domain_min
    if abs( span ) < _EPSILON:
        return ( pixel_min + pixel_max ) / 2.0
    ratio = ( value - domain_min ) / span
    return pixel_min + ( ratio * ( pixel_max - pixel_min ))


def _round( value : float ) -> float:
    return round( value, 2 )


def _validate( chart : LineChart ):
    if chart.chrome not in CHART_CHROME:
        raise ValueError(
            f'Unknown chart chrome "{chart.chrome}". '
            f'Available: {", ".join( sorted( CHART_CHROME ))}.'
        )
    for series in chart.series:
        if len( series.values ) != len( chart.x ):
            raise ValueError(
                f'Series "{series.label}" has {len( series.values )} values but the '
                f'x axis has {len( chart.x )} positions; they must match.'
            )
    return
