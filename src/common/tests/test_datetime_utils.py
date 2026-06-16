import datetime
from zoneinfo import ZoneInfo

from django.test import TestCase

from common import datetime_utils as dt
from common.datetime_utils import TIMEZONE_NAME_LIST, DEFAULT_TIME_ZONE_NAME

UTC = datetime.timezone.utc


class DistantPastTest(TestCase):

    def test_default_is_1970_01_02_utc(self):
        d = dt.distant_past()
        self.assertEqual(d, datetime.datetime(1970, 1, 2, tzinfo=UTC))
        self.assertIsNotNone(d.tzinfo)

    def test_with_tzname_keeps_same_instant(self):
        d = dt.distant_past('America/New_York')
        self.assertEqual(d, datetime.datetime(1970, 1, 2, tzinfo=UTC))   # same instant
        self.assertEqual(d.tzinfo, ZoneInfo('America/New_York'))


class ComponentsToDatetimeUtcTest(TestCase):

    def test_utc_passthrough(self):
        r = dt.components_to_datetime_utc(datetime.date(2024, 6, 15), datetime.time(12, 0), 'UTC')
        self.assertEqual(r, datetime.datetime(2024, 6, 15, 12, 0, tzinfo=UTC))

    def test_new_york_summer_offset(self):   # EDT = UTC-4
        r = dt.components_to_datetime_utc(datetime.date(2024, 6, 15), datetime.time(12, 0),
                                          'America/New_York')
        self.assertEqual(r, datetime.datetime(2024, 6, 15, 16, 0, tzinfo=UTC))

    def test_unknown_tz_falls_back_to_utc(self):
        r = dt.components_to_datetime_utc(datetime.date(2024, 6, 15), datetime.time(12, 0), 'Not/AZone')
        self.assertEqual(r, datetime.datetime(2024, 6, 15, 12, 0, tzinfo=UTC))


class DayRangeUtcTest(TestCase):

    def test_utc_day_bounds(self):
        start, end = dt.day_range_utc(datetime.date(2024, 6, 15), 'UTC')
        self.assertEqual(start, datetime.datetime(2024, 6, 15, 0, 0, tzinfo=UTC))
        self.assertEqual(end, datetime.datetime(2024, 6, 15, 23, 59, 59, 999999, tzinfo=UTC))

    def test_new_york_day_crosses_utc_midnight(self):   # EDT = UTC-4
        start, end = dt.day_range_utc(datetime.date(2024, 6, 15), 'America/New_York')
        self.assertEqual(start, datetime.datetime(2024, 6, 15, 4, 0, tzinfo=UTC))
        self.assertEqual(end, datetime.datetime(2024, 6, 16, 3, 59, 59, 999999, tzinfo=UTC))


class ChangeTimezoneTest(TestCase):

    def test_converts_preserving_instant(self):
        utc_dt = datetime.datetime(2024, 6, 15, 16, 0, tzinfo=UTC)
        ny = dt.change_timezone(utc_dt, 'America/New_York')
        self.assertEqual(ny.hour, 12)        # 16:00 UTC == 12:00 EDT
        self.assertEqual(ny, utc_dt)         # same instant

    def test_unknown_tz_falls_back_to_utc(self):
        utc_dt = datetime.datetime(2024, 6, 15, 16, 0, tzinfo=UTC)
        r = dt.change_timezone(utc_dt, 'Bogus/Zone')
        self.assertEqual(r.utcoffset(), datetime.timedelta(0))


class WeekOfMonthTest(TestCase):

    def test_saturday_start_month(self):     # June 2024 begins on a Saturday
        self.assertEqual(dt.week_of_month(datetime.datetime(2024, 6, 1)), 1)
        self.assertEqual(dt.week_of_month(datetime.datetime(2024, 6, 2)), 2)   # Sunday -> new week
        self.assertEqual(dt.week_of_month(datetime.datetime(2024, 6, 9)), 3)

    def test_sunday_start_month(self):       # September 2024 begins on a Sunday
        self.assertEqual(dt.week_of_month(datetime.datetime(2024, 9, 1)), 1)
        self.assertEqual(dt.week_of_month(datetime.datetime(2024, 9, 8)), 2)
        self.assertEqual(dt.week_of_month(datetime.datetime(2024, 9, 30)), 5)


class AddMonthsYearsTest(TestCase):

    def test_add_months_clamps_to_leap_feb(self):
        self.assertEqual(dt.add_months(datetime.date(2024, 1, 31), 1), datetime.date(2024, 2, 29))

    def test_add_months_clamps_to_nonleap_feb(self):
        self.assertEqual(dt.add_months(datetime.date(2023, 1, 31), 1), datetime.date(2023, 2, 28))

    def test_add_months_negative(self):
        self.assertEqual(dt.add_months(datetime.date(2024, 3, 15), -2), datetime.date(2024, 1, 15))

    def test_add_years_clamps_leap_day(self):
        self.assertEqual(dt.add_years(datetime.date(2024, 2, 29), 1), datetime.date(2025, 2, 28))

    def test_add_years_preserves_time(self):
        d = datetime.datetime(2024, 6, 15, 10, 30, tzinfo=UTC)
        self.assertEqual(dt.add_years(d, 1), datetime.datetime(2025, 6, 15, 10, 30, tzinfo=UTC))


class ElapsedMonthsTest(TestCase):

    def test_ignores_day_of_month(self):
        self.assertEqual(dt.elapsed_months(datetime.date(2024, 4, 30), datetime.date(2024, 5, 1)), 1)

    def test_full_year(self):
        self.assertEqual(dt.elapsed_months(datetime.date(2024, 1, 1), datetime.date(2025, 1, 1)), 12)

    def test_same_month_is_zero(self):
        self.assertEqual(dt.elapsed_months(datetime.date(2024, 6, 5), datetime.date(2024, 6, 25)), 0)

    def test_backwards_is_negative(self):
        self.assertEqual(dt.elapsed_months(datetime.date(2024, 6, 1), datetime.date(2024, 3, 1)), -3)


class TimezoneNameListTest(TestCase):

    def test_includes_utc_and_all_resolvable(self):
        self.assertIn('UTC', TIMEZONE_NAME_LIST)
        self.assertEqual(DEFAULT_TIME_ZONE_NAME, 'UTC')
        for name in TIMEZONE_NAME_LIST:
            ZoneInfo(name)   # raises if not a valid IANA zone
