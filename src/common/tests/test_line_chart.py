from django import template
from django.test import SimpleTestCase
from django.utils.safestring import SafeString

from common.line_chart import (
    CHROME_FULL,
    CHROME_SPARKLINE,
    ChartTick,
    LineChart,
    LineChartSeries,
    build_geometry,
)
from common.templatetags.charts import line_chart as line_chart_tag


def _series( values, label = 'series', color = '#123456' ):
    return LineChartSeries( values = values, label = label, color = color )


def _parse_points( points : str ):
    return [ tuple( float( n ) for n in pair.split( ',' ))
             for pair in points.split() ]


class BuildGeometryScalingTestCase( SimpleTestCase ):

    def test_x_positions_scale_proportionally_to_value(self):
        # A variable-width axis: the gap 1->3 is twice the gap 0->1, so the middle
        # point must sit one-third of the way across the plot, not at the midpoint.
        chart    = LineChart( x = [ 0.0, 1.0, 3.0 ], series = [ _series([ 5, 5, 5 ]) ],
                              chrome = CHROME_FULL )
        geometry = build_geometry( chart )
        points   = _parse_points( geometry.series[0].points )
        plot     = geometry.plot

        span     = plot.inner_width
        self.assertAlmostEqual( points[0][0], plot.left, places = 1 )
        self.assertAlmostEqual( points[2][0], plot.right, places = 1 )
        self.assertAlmostEqual( points[1][0], plot.left + ( span / 3.0 ), places = 1 )

    def test_one_point_per_x_position(self):
        chart    = LineChart( x = [ 0.0, 1.0, 2.0, 3.0 ], series = [ _series([ 1, 2, 3, 4 ]) ] )
        geometry = build_geometry( chart )
        self.assertEqual( len( _parse_points( geometry.series[0].points )), 4 )

    def test_y_grows_downward_higher_value_smaller_pixel(self):
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 10, 20 ]) ] )
        geometry = build_geometry( chart )
        (_, y_low), (_, y_high) = _parse_points( geometry.series[0].points )
        # 20 is the larger value, so it draws nearer the top (smaller y pixel).
        self.assertLess( y_high, y_low )


class ZeroBaselineTestCase( SimpleTestCase ):

    def test_zero_line_when_values_cross_zero(self):
        chart    = LineChart( x = [ 0.0, 1.0, 2.0 ], series = [ _series([ -100, 0, 100 ]) ] )
        geometry = build_geometry( chart )
        midline  = ( geometry.plot.top + geometry.plot.bottom ) / 2.0
        self.assertIsNotNone( geometry.zero_line_y )
        self.assertAlmostEqual( geometry.zero_line_y, midline, places = 6 )

    def test_no_zero_line_when_all_positive(self):
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 10, 20 ]) ] )
        geometry = build_geometry( chart )
        self.assertIsNone( geometry.zero_line_y )

    def test_no_zero_line_when_all_negative(self):
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ -10, -20 ]) ] )
        geometry = build_geometry( chart )
        self.assertIsNone( geometry.zero_line_y )

    def test_y_domain_override_sets_axis_extent(self):
        # With an explicit domain of [-100, 300], value 100 sits halfway up the plot.
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 100, 100 ]) ],
                              y_min = -100.0, y_max = 300.0 )
        geometry = build_geometry( chart )
        midline  = ( geometry.plot.top + geometry.plot.bottom ) / 2.0
        (_, y0), (_, y1) = _parse_points( geometry.series[0].points )
        self.assertAlmostEqual( y0, midline, places = 6 )
        self.assertAlmostEqual( y1, midline, places = 6 )

    def test_include_zero_false_uses_data_bounds(self):
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 10, 20 ]) ],
                              include_zero = False )
        geometry = build_geometry( chart )
        # Data min 10 is now the plot floor, so the lower point sits at the bottom.
        (_, y0), (_, y1) = _parse_points( geometry.series[0].points )
        self.assertAlmostEqual( max( y0, y1 ), geometry.plot.bottom, places = 6 )


class ChromeTestCase( SimpleTestCase ):

    def test_sparkline_has_no_axes_ticks_or_gridlines(self):
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 1, 2 ]) ],
                              chrome = CHROME_SPARKLINE )
        geometry = build_geometry( chart )
        self.assertFalse( geometry.show_axes )
        self.assertEqual( geometry.gridlines, [] )
        self.assertEqual( geometry.y_ticks, [] )
        self.assertEqual( geometry.x_ticks, [] )
        self.assertEqual( len( geometry.series ), 1 )

    def test_full_generates_axes_ticks_and_gridlines(self):
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 0, 100 ]) ],
                              chrome = CHROME_FULL )
        geometry = build_geometry( chart )
        self.assertTrue( geometry.show_axes )
        self.assertTrue( geometry.y_ticks )
        self.assertEqual( len( geometry.gridlines ), len( geometry.y_ticks ))
        self.assertEqual( len( geometry.x_ticks ), 2 )   # first and last x

    def test_sparkline_plot_area_smaller_than_full(self):
        base       = dict( x = [ 0.0, 1.0 ], series = [ _series([ 1, 2 ]) ] )
        sparkline  = build_geometry( LineChart( chrome = CHROME_SPARKLINE, **base ))
        full       = build_geometry( LineChart( chrome = CHROME_FULL, **base ))
        # `full` reserves margins for axes/labels, so its plot starts further right.
        self.assertGreater( full.plot.left, sparkline.plot.left )


class TicksTestCase( SimpleTestCase ):

    def test_custom_ticks_are_used(self):
        ticks    = [ ChartTick( value = 0.0, label = '$0' ),
                     ChartTick( value = 50.0, label = '$50' ) ]
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 0, 100 ]) ],
                              y_ticks = ticks )
        geometry = build_geometry( chart )
        self.assertEqual( [ tick.label for tick in geometry.y_ticks ], [ '$0', '$50' ] )

    def test_ticks_outside_domain_are_dropped(self):
        ticks    = [ ChartTick( value = -999.0, label = 'below' ),
                     ChartTick( value = 50.0, label = 'ok' ),
                     ChartTick( value = 999.0, label = 'above' ) ]
        chart    = LineChart( x = [ 0.0, 1.0 ], series = [ _series([ 0, 100 ]) ],
                              y_ticks = ticks )
        geometry = build_geometry( chart )
        self.assertEqual( [ tick.label for tick in geometry.y_ticks ], [ 'ok' ] )


class DegenerateInputTestCase( SimpleTestCase ):

    def test_all_equal_values_do_not_crash_and_pad_domain(self):
        chart    = LineChart( x = [ 0.0, 1.0, 2.0 ], series = [ _series([ 0, 0, 0 ]) ] )
        geometry = build_geometry( chart )
        points   = _parse_points( geometry.series[0].points )
        self.assertEqual( len( points ), 3 )
        # Flat data is padded to a range, so a zero series lands mid-plot.
        midline  = ( geometry.plot.top + geometry.plot.bottom ) / 2.0
        for _, y in points:
            self.assertAlmostEqual( y, midline, places = 6 )

    def test_single_x_position_does_not_divide_by_zero(self):
        chart    = LineChart( x = [ 5.0 ], series = [ _series([ 42 ]) ] )
        geometry = build_geometry( chart )
        (x, _), = _parse_points( geometry.series[0].points )
        center  = ( geometry.plot.left + geometry.plot.right ) / 2.0
        self.assertAlmostEqual( x, center, places = 6 )

    def test_empty_series_renders_without_lines(self):
        chart    = LineChart( x = [], series = [] )
        geometry = build_geometry( chart )
        self.assertEqual( geometry.series, [] )


class ValidationTestCase( SimpleTestCase ):

    def test_series_length_must_match_x(self):
        chart = LineChart( x = [ 0.0, 1.0, 2.0 ], series = [ _series([ 1, 2 ]) ] )
        with self.assertRaises( ValueError ):
            build_geometry( chart )

    def test_unknown_chrome_rejected(self):
        chart = LineChart( x = [ 0.0 ], series = [ _series([ 1 ]) ], chrome = 'huge' )
        with self.assertRaises( ValueError ):
            build_geometry( chart )


class LineChartTagTestCase( SimpleTestCase ):

    def _chart( self, **overrides ):
        params = dict( x = [ 0.0, 1.0, 2.0 ],
                       series = [ _series([ -10, 0, 20 ], color = '#ff0000' ) ] )
        params.update( overrides )
        return LineChart( **params )

    def test_returns_safe_svg_scaled_by_viewbox(self):
        result = line_chart_tag( self._chart() )
        self.assertIsInstance( result, SafeString )
        self.assertIn( '<svg', result )
        self.assertIn( 'viewBox=', result )
        self.assertIn( '<polyline', result )
        # No fixed pixel size on the root <svg>: it scales to its CSS container.
        svg_open_tag = result[ : result.index( '>' ) ]
        self.assertNotIn( ' width=', svg_open_tag )
        self.assertNotIn( ' height=', svg_open_tag )

    def test_series_colour_is_emitted(self):
        result = line_chart_tag( self._chart() )
        self.assertIn( 'stroke="#ff0000"', result )

    def test_aria_label_makes_it_meaningful(self):
        result = line_chart_tag( self._chart(), aria_label = 'Net worth' )
        self.assertIn( 'role="img"', result )
        self.assertIn( 'aria-label="Net worth"', result )

    def test_decorative_without_aria_label(self):
        result = line_chart_tag( self._chart() )
        self.assertIn( 'aria-hidden="true"', result )

    def test_full_chrome_has_tick_text_sparkline_does_not(self):
        full       = line_chart_tag( self._chart( chrome = CHROME_FULL ))
        sparkline  = line_chart_tag( self._chart( chrome = CHROME_SPARKLINE ))
        self.assertIn( '<text', full )
        self.assertNotIn( '<text', sparkline )

    def test_non_linechart_argument_rejected(self):
        with self.assertRaises( template.TemplateSyntaxError ):
            line_chart_tag( { 'not': 'a chart' } )

    def test_title_is_rendered_as_svg_title(self):
        result = line_chart_tag( self._chart(), title = 'Latest run' )
        self.assertIn( '<title>Latest run</title>', result )
