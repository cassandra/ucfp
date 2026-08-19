"""Constants for the organization (household) app.

The curated display-timezone list: a deliberately small, ordered set of IANA zones -- one common
choice per region, not every zone -- so the settings picker stays short and simple. It is the single
source of truth for both the model field's choices and the settings form.
"""

# The default display timezone for a new household: US Central.
DEFAULT_TIMEZONE_NAME = 'America/Chicago'

# Ordered roughly by region (UTC, Pacific, the Americas west-to-east, Europe, Africa, the Middle East,
# Asia, Australia), so the picker reads geographically rather than alphabetically.
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

# The (value, label) pairs for a choice field -- the IANA name as the stored value, and a friendlier
# label with the underscores spaced out for reading (e.g. 'America/New York').
TIMEZONE_CHOICES = [ ( name, name.replace( '_', ' ' ) ) for name in TIMEZONE_NAME_LIST ]
