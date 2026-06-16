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
