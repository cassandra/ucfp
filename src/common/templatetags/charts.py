"""
Chart template tags for server-side SVG rendering.

Renders a `LineChart` (see ``common/line_chart.py``) as self-contained inline SVG,
with no external dependencies. The chart is domain-agnostic: callers build the
`LineChart` (series, colours, ticks) and pass it in.

Usage:
    {% load charts %}
    {% line_chart net_worth_chart aria_label="Net worth over time" %}
    {% line_chart run_chart css_class="run-output-chart" %}
"""
from django import template
from django.template.loader import get_template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from common.line_chart import CHART_CHROME, LineChart, build_geometry

register = template.Library()

_CHART_TEMPLATE = 'charts/line_chart.svg'
_LEGEND_TEMPLATE = 'charts/legend.html'


@register.simple_tag
def line_chart( chart, css_class = '', aria_label = None, title = None ):
    """
    Render a `LineChart` as inline SVG.

    Args:
        chart (LineChart): The chart specification to render.
        css_class (str): Additional CSS classes for the root <svg>. Default: ''.
        aria_label (str): Accessibility label. If provided, the chart is meaningful
                          (role="img"); if None it is decorative (aria-hidden).
        title (str): Tooltip / accessible <title> text. Default: None.

    Returns:
        SafeString: The rendered SVG.

    Raises:
        template.TemplateSyntaxError: If `chart` is not a LineChart or its chrome
                                      is not recognised.
    """
    if not isinstance( chart, LineChart ):
        raise template.TemplateSyntaxError(
            f'{{% line_chart %}} expects a LineChart, got {type( chart ).__name__}.'
        )
    if chart.chrome not in CHART_CHROME:
        raise template.TemplateSyntaxError(
            f'Chart chrome "{chart.chrome}" is not available. '
            f'Available: {", ".join( sorted( CHART_CHROME ))}.'
        )

    geometry = build_geometry( chart )

    # Dynamic values are escaped; the assembled attribute string is marked safe so
    # it is not double-escaped when inserted via {{ accessibility_attrs }}.
    if aria_label:
        accessibility_attrs = mark_safe( f'role="img" aria-label="{escape( aria_label )}"' )
    else:
        accessibility_attrs = mark_safe( 'aria-hidden="true"' )

    context = {
        'geometry'             : geometry,
        'chrome'               : chart.chrome,
        'css_class'            : escape( css_class ),
        'accessibility_attrs'  : accessibility_attrs,
        'title_text'           : title,
    }
    return mark_safe( get_template( _CHART_TEMPLATE ).render( context ))


@register.simple_tag
def chart_legend( chart ):
    """
    Render an HTML legend for a `LineChart` -- a colour swatch and label per series.

    This is the secondary encoding a multi-series chart needs (colour is never the
    sole cue): the swatch carries the series colour, the label stays in text ink.

    Raises:
        template.TemplateSyntaxError: If `chart` is not a LineChart.
    """
    if not isinstance( chart, LineChart ):
        raise template.TemplateSyntaxError(
            f'{{% chart_legend %}} expects a LineChart, got {type( chart ).__name__}.'
        )
    return mark_safe( get_template( _LEGEND_TEMPLATE ).render( { 'series': chart.series } ))
