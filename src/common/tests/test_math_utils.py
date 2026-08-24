from django.test import TestCase

import common.math_utils as math_utils


class MathUtilsTestCase(TestCase):

    def test_jaccard_coefficient(self):
        test_data_list = [
            { 'tuple_1': ( 0, 0 ), 'tuple_2': ( 0, 0 ), 'expect': 1.0 },
            { 'tuple_1': ( 0, 0 ), 'tuple_2': ( 1, 1 ), 'expect': 0.0 },
            { 'tuple_1': ( 1, 1 ), 'tuple_2': ( 1, 1 ), 'expect': 1.0 },
            { 'tuple_1': ( 1, 1 ), 'tuple_2': ( 0, 0 ), 'expect': 0.0 },
            { 'tuple_1': ( 0, 1 ), 'tuple_2': ( 0, 0 ), 'expect': 0.0 },
            { 'tuple_1': ( 0, 1 ), 'tuple_2': ( 1, 1 ), 'expect': 0.0 },
            { 'tuple_1': ( 0, 2 ), 'tuple_2': ( 0, 1 ), 'expect': 0.5 },
            { 'tuple_1': ( 0, 2 ), 'tuple_2': ( 0, 2 ), 'expect': 1.0 },
            { 'tuple_1': ( 0, 2 ), 'tuple_2': ( 0, 10 ), 'expect': 0.2 },
        ]

        for test_data in test_data_list:
            result = math_utils.jaccard_coefficient( test_data['tuple_1'], test_data['tuple_2'] )
            self.assertAlmostEqual( test_data['expect'], result, 6, test_data )
            continue
        return


class NiceTicksTestCase(TestCase):

    def test_produces_round_steps_covering_the_range(self):
        ticks = math_utils.nice_ticks( 0.0, 1_000_000.0, 4 )
        self.assertEqual( ticks, [ 0.0, 250_000.0, 500_000.0, 750_000.0, 1_000_000.0 ] )

    def test_range_extends_outward_to_round_bounds(self):
        # 10..92 with a step of 25 rounds out to 0..100 so both ends are round.
        ticks = math_utils.nice_ticks( 10.0, 92.0, 4 )
        self.assertEqual( ticks[ 0 ], 0.0 )
        self.assertEqual( ticks[ -1 ], 100.0 )
        self.assertLessEqual( ticks[ 0 ], 10.0 )
        self.assertGreaterEqual( ticks[ -1 ], 92.0 )

    def test_spans_negative_through_positive(self):
        ticks = math_utils.nice_ticks( -50_000.0, 900_000.0, 4 )
        self.assertLessEqual( ticks[ 0 ], -50_000.0 )
        self.assertGreaterEqual( ticks[ -1 ], 900_000.0 )
        self.assertIn( 0.0, ticks )

    def test_steps_are_uniform(self):
        ticks = math_utils.nice_ticks( 0.0, 37.0, 5 )
        steps = { round( b - a, 9 ) for a, b in zip( ticks, ticks[ 1: ] ) }
        self.assertEqual( len( steps ), 1 )

    def test_degenerate_range_returns_single_value(self):
        self.assertEqual( math_utils.nice_ticks( 5.0, 5.0, 4 ), [ 5.0 ] )
        self.assertEqual( math_utils.nice_ticks( 5.0, 1.0, 4 ), [ 5.0 ] )
