"""
Date/time helpers built on the standard library's zoneinfo and python-dateutil.

This is the modernized successor to the old ``datetimeproxy`` module. The
"proxy" name reflected its original job: routing all time access through a
single overridable ``now()`` so tests could control the wall clock. That job
now belongs to a real time-mocking library (time-machine) -- tests travel the
global clock and code calls ``django.utils.timezone.now()`` directly -- so the
proxy / now / set / reset machinery is gone.

What remains are the genuinely reusable helpers that the standard library and
Django do NOT already cover, all timezone-aware via ``zoneinfo`` (pytz is no
longer used). Anything stdlib/Django now covers (ISO/epoch parsing, RFC2822,
``date.fromisoformat``, humanized "time since", timezone-name validation) has
been dropped in favor of the built-in equivalents, and domain-specific helpers
(calendar view ranges, EXIF/GPS timezone lookup, etc.) belong in the app that
needs them, not here.
"""
import datetime
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)

# Fallback used when a caller passes an unrecognized timezone name.
DEFAULT_TIME_ZONE_NAME = 'UTC'

# A curated, ordered subset of IANA timezone names suitable for a user-facing
# timezone picker (the full zoneinfo set is too large for a usable dropdown).
# Ordered roughly west-to-east within each region.
TIMEZONE_NAME_LIST = [
    # UTC
    'UTC',
    # Pacific
    'Pacific/Honolulu',
    'Pacific/Auckland',
    # Americas (north to south, west to east)
    'America/Anchorage',
    'America/Vancouver',
    'America/Los_Angeles',
    'America/Denver',
    'America/Chicago',
    'America/New_York',
    'America/Toronto',
    'America/Mexico_City',
    'America/Sao_Paulo',
    'America/Argentina/Buenos_Aires',
    # Europe (west to east)
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Athens',
    'Europe/Istanbul',
    'Europe/Moscow',
    # Africa (north to south)
    'Africa/Cairo',
    'Africa/Lagos',
    'Africa/Johannesburg',
    # Middle East
    'Asia/Dubai',
    # Asia (west to east)
    'Asia/Kolkata',
    'Asia/Bangkok',
    'Asia/Jakarta',
    'Asia/Singapore',
    'Asia/Hong_Kong',
    'Asia/Shanghai',
    'Asia/Seoul',
    'Asia/Tokyo',
    # Australia (west to east)
    'Australia/Perth',
    'Australia/Sydney',
    'Australia/Melbourne',
]


def _safe_zoneinfo( tzname ):
    """Resolve a timezone name to a ZoneInfo, falling back to
    DEFAULT_TIME_ZONE_NAME (with a warning) if the name is unrecognized."""
    try:
        return ZoneInfo( tzname )
    except ( ZoneInfoNotFoundError, ValueError ) as e:
        logger.warning( "Unrecognized time zone '%s' (%s); falling back to %s",
                        tzname, e, DEFAULT_TIME_ZONE_NAME )
        return ZoneInfo( DEFAULT_TIME_ZONE_NAME )


def distant_past( tzname = None ):
    """A fixed 'long ago' timezone-aware datetime, useful as a sentinel/initial
    value for 'last seen' style comparisons. Uses 1970-01-02 UTC (one day past
    the epoch) to stay clear of underflow when timezone conversions or
    subtractions push it earlier."""
    the_dt = datetime.datetime( 1970, 1, 2, tzinfo = datetime.timezone.utc )
    if tzname is None:
        return the_dt
    return the_dt.astimezone( _safe_zoneinfo( tzname ))


def components_to_datetime_utc( the_date, the_time, tzname ):
    """Interpret a naive date + time as wall-clock time in ``tzname`` and return
    the equivalent timezone-aware UTC datetime."""
    local_dt = datetime.datetime.combine( the_date, the_time, tzinfo = _safe_zoneinfo( tzname ))
    return local_dt.astimezone( datetime.timezone.utc )


def day_range_utc( the_date, tzname ):
    """Return (start_utc, end_utc): the UTC datetimes bounding the calendar day
    ``the_date`` as it occurs in ``tzname``."""
    tz = _safe_zoneinfo( tzname )
    start = datetime.datetime.combine( the_date, datetime.time.min, tzinfo = tz )
    end   = datetime.datetime.combine( the_date, datetime.time.max, tzinfo = tz )
    return ( start.astimezone( datetime.timezone.utc ),
             end.astimezone( datetime.timezone.utc ) )


def change_timezone( the_datetime, tzname ):
    """Return ``the_datetime`` converted to ``tzname`` (falling back to
    DEFAULT_TIME_ZONE_NAME if the name is unrecognized)."""
    return the_datetime.astimezone( _safe_zoneinfo( tzname ))


def week_of_month( the_datetime ):
    """Return the week of the month for ``the_datetime``, counting weeks that
    start on Sunday."""
    first_day = the_datetime.replace( day = 1 )
    if first_day.weekday() == 6:   # Sunday
        adjustment = -1
    else:
        adjustment = first_day.weekday()
    return 1 + int( ( the_datetime.day + adjustment ) / 7 )


def add_months( start_dt, num_months ):
    """Add ``num_months`` to ``start_dt`` (may be negative). Month-end and leap
    years are handled by dateutil: e.g. Jan 31 + 1 month -> Feb 28/29."""
    return start_dt + relativedelta( months = num_months )


def add_years( start_dt, num_years ):
    """Add ``num_years`` to ``start_dt`` (may be negative). Feb 29 in a
    non-leap target year clamps to Feb 28."""
    return start_dt + relativedelta( years = num_years )


def elapsed_months( start_date, end_date ):
    """Whole-calendar-month difference between two dates, ignoring day-of-month.
    e.g. there is one month between April 30 and May 1."""
    return ( end_date.year - start_date.year ) * 12 + ( end_date.month - start_date.month )
