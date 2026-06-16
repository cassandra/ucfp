from django.test import TestCase

import common.humanize_utils as humanize_utils


class HumanizeUtilsTestCase(TestCase):

    def test_get_humanized_secs(self):

        data_list = [
            { 'secs': 0,
              'expect': '0 secs',
              },
            { 'secs': 1,
              'expect': '1 sec',
              },
            { 'secs': 2,
              'expect': '2 secs',
              },
            { 'secs': 59,
              'expect': '59 secs',
              },
            { 'secs': 60,
              'expect': '1 min',
              },
            { 'secs': 61,
              'expect': '1 min, 1 sec',
              },
            { 'secs': 65,
              'expect': '1 min, 5 secs',
              },
            { 'secs': 120,
              'expect': '2 mins',
              },
            { 'secs': 121,
              'expect': '2 mins, 1 sec',
              },
            { 'secs': 126,
              'expect': '2 mins, 6 secs',
              },
            { 'secs': 60 * 60 - 1,
              'expect': '59 mins, 59 secs',
              },
            { 'secs': 60 * 60,
              'expect': '1 hr',
              },
            { 'secs': 60 * 60 + 1,
              'expect': '1 hr, 1 sec',
              },
            { 'secs': 60 * 60 + 24,
              'expect': '1 hr, 24 secs',
              },
            { 'secs': 60 * 60 + 61,
              'expect': '1 hr, 1 min, 1 sec',
              },
            { 'secs': 60 * 60 + 68,
              'expect': '1 hr, 1 min, 8 secs',
              },
            { 'secs': 60 * 60 + 120,
              'expect': '1 hr, 2 mins',
              },
            { 'secs': 60 * 60 + 121,
              'expect': '1 hr, 2 mins, 1 sec',
              },
            { 'secs': 60 * 60 + 127,
              'expect': '1 hr, 2 mins, 7 secs',
              },
            { 'secs': 2 * 60 * 60 + 127,
              'expect': '2 hrs, 2 mins, 7 secs',
              },
            { 'secs': 24 * 60 * 60 + 1,
              'expect': '1 day, 1 sec',
              },
            { 'secs': 24 * 60 * 60 + 11,
              'expect': '1 day, 11 secs',
              },
            { 'secs': 24 * 60 * 60 + 60,
              'expect': '1 day, 1 min',
              },
            { 'secs': 24 * 60 * 60 + 3669,
              'expect': '1 day, 1 hr, 1 min, 9 secs',
              },
        ]

        for data in data_list:
            self.assertEqual( data['expect'], humanize_utils.get_humanized_secs( data['secs'] ), data )
            continue
        return

    def test_get_humanized_number(self):

        data_list = [
            ( 0, 'zero' ),
            ( 1, '1st' ),
            ( 2, '2nd' ),
            ( 3, '3rd' ),
            ( 4, '4th' ),
            ( 5, '5th' ),
            ( 6, '6th' ),
            ( 7, '7th' ),
            ( 8, '8th' ),
            ( 9, '9th' ),
            ( 10, '10th' ),
            ( 11, '11th' ),
            ( 12, '12th' ),
            ( 13, '13th' ),
            ( 14, '14th' ),
            ( 15, '15th' ),
            ( 16, '16th' ),
            ( 17, '17th' ),
            ( 18, '18th' ),
            ( 19, '19th' ),
            ( 20, '20th' ),
            ( 21, '21st' ),
            ( 22, '22nd' ),
            ( 23, '23rd' ),
            ( 24, '24th' ),
            ( 25, '25th' ),
            ( 30, '30th' ),
            ( 31, '31st' ),
            ( 42, '42nd' ),
            ( 53, '53rd' ),
            ( 64, '64th' ),
            ( 101, '101st' ),
            ( 111, '111th' ),
            ( 1025, '1,025th' ),
            ( 10002, '10,002nd' ),
            ( 10012, '10,012th' ),
        ]

        for value, expected_result in data_list:
            self.assertEqual( expected_result, humanize_utils.get_humanized_number(value), f'{value}' )
            continue
        return
