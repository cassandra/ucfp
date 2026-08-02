"""US state (subdivision) income tax -- the simplified per-state model.

State income tax is modeled as a SINGLE representative flat rate per state applied to federal
AGI, deliberately NOT the state's real brackets, deductions, or credits. `USState` is the pick a
household makes; `representative_rate` is the rate the People-section form auto-fills from that
pick (the user may override, so the Profile stores its own rate and the engine reads that -- this
table is only the UI's starting point). No-income-tax states (e.g. Texas, Florida) are 0.

The rates are approximate effective rates for a middle / upper-middle household in today's dollars,
chosen to make the forecast *somewhat* more accurate, not to reproduce any state's tax code. They
are plain data: adjust a number here without touching structure. Named `subdivision_tax` (not
`state`) because `us/state.py` already holds the engine's carryforward tax *state*.
"""
from dataclasses import dataclass
from decimal import Decimal

from common.labeled_enum import LabeledEnum
from common.rate import Rate, ZERO_RATE


@dataclass( frozen = True )
class StateIncomeTax:
    """A household's state income-tax policy: a flat `rate` on federal AGI, less the state's exemption
    of retirement income. `social_security_exempt` and `retirement_exempt` are the fractions (0..1) of
    taxable Social Security and of pension + pre-tax retirement-distribution income the state removes
    from the base -- 0 fully taxes it, 1 fully exempts it. The default is no state tax (zero rate, no
    exemptions); a rate with zero exemptions is the earlier flat-on-AGI model."""

    rate                   : Rate    = ZERO_RATE
    social_security_exempt : Decimal = Decimal( '0' )
    retirement_exempt      : Decimal = Decimal( '0' )


class USState( LabeledEnum ):
    """A US state (plus the District of Columbia) a household files in -- the selector that
    auto-fills a representative state income-tax rate. US-specific; lives here, not in the neutral
    jurisdiction layer."""

    ALABAMA        = ( 'Alabama'       , 'Alabama state income tax.' )
    ALASKA         = ( 'Alaska'        , 'Alaska -- no state income tax.' )
    ARIZONA        = ( 'Arizona'       , 'Arizona state income tax.' )
    ARKANSAS       = ( 'Arkansas'      , 'Arkansas state income tax.' )
    CALIFORNIA     = ( 'California'    , 'California state income tax.' )
    COLORADO       = ( 'Colorado'      , 'Colorado state income tax.' )
    CONNECTICUT    = ( 'Connecticut'   , 'Connecticut state income tax.' )
    DELAWARE       = ( 'Delaware'      , 'Delaware state income tax.' )
    FLORIDA        = ( 'Florida'       , 'Florida -- no state income tax.' )
    GEORGIA        = ( 'Georgia'       , 'Georgia state income tax.' )
    HAWAII         = ( 'Hawaii'        , 'Hawaii state income tax.' )
    IDAHO          = ( 'Idaho'         , 'Idaho state income tax.' )
    ILLINOIS       = ( 'Illinois'      , 'Illinois state income tax.' )
    INDIANA        = ( 'Indiana'       , 'Indiana state income tax.' )
    IOWA           = ( 'Iowa'          , 'Iowa state income tax.' )
    KANSAS         = ( 'Kansas'        , 'Kansas state income tax.' )
    KENTUCKY       = ( 'Kentucky'      , 'Kentucky state income tax.' )
    LOUISIANA      = ( 'Louisiana'     , 'Louisiana state income tax.' )
    MAINE          = ( 'Maine'         , 'Maine state income tax.' )
    MARYLAND       = ( 'Maryland'      , 'Maryland state income tax (state only; excludes local).' )
    MASSACHUSETTS  = ( 'Massachusetts' , 'Massachusetts state income tax.' )
    MICHIGAN       = ( 'Michigan'      , 'Michigan state income tax.' )
    MINNESOTA      = ( 'Minnesota'     , 'Minnesota state income tax.' )
    MISSISSIPPI    = ( 'Mississippi'   , 'Mississippi state income tax.' )
    MISSOURI       = ( 'Missouri'      , 'Missouri state income tax.' )
    MONTANA        = ( 'Montana'       , 'Montana state income tax.' )
    NEBRASKA       = ( 'Nebraska'      , 'Nebraska state income tax.' )
    NEVADA         = ( 'Nevada'        , 'Nevada -- no state income tax.' )
    NEW_HAMPSHIRE  = ( 'New Hampshire' , 'New Hampshire -- no tax on wage income.' )
    NEW_JERSEY     = ( 'New Jersey'    , 'New Jersey state income tax.' )
    NEW_MEXICO     = ( 'New Mexico'    , 'New Mexico state income tax.' )
    NEW_YORK       = ( 'New York'      , 'New York state income tax (state only; excludes NYC local).' )
    NORTH_CAROLINA = ( 'North Carolina', 'North Carolina state income tax.' )
    NORTH_DAKOTA   = ( 'North Dakota'  , 'North Dakota state income tax.' )
    OHIO           = ( 'Ohio'          , 'Ohio state income tax.' )
    OKLAHOMA       = ( 'Oklahoma'      , 'Oklahoma state income tax.' )
    OREGON         = ( 'Oregon'        , 'Oregon state income tax.' )
    PENNSYLVANIA   = ( 'Pennsylvania'  , 'Pennsylvania state income tax.' )
    RHODE_ISLAND   = ( 'Rhode Island'  , 'Rhode Island state income tax.' )
    SOUTH_CAROLINA = ( 'South Carolina', 'South Carolina state income tax.' )
    SOUTH_DAKOTA   = ( 'South Dakota'  , 'South Dakota -- no state income tax.' )
    TENNESSEE      = ( 'Tennessee'     , 'Tennessee -- no state income tax.' )
    TEXAS          = ( 'Texas'         , 'Texas -- no state income tax.' )
    UTAH           = ( 'Utah'          , 'Utah state income tax.' )
    VERMONT        = ( 'Vermont'       , 'Vermont state income tax.' )
    VIRGINIA       = ( 'Virginia'      , 'Virginia state income tax.' )
    WASHINGTON     = ( 'Washington'    , 'Washington -- no tax on ordinary income.' )
    WEST_VIRGINIA  = ( 'West Virginia' , 'West Virginia state income tax.' )
    WISCONSIN      = ( 'Wisconsin'     , 'Wisconsin state income tax.' )
    WYOMING        = ( 'Wyoming'       , 'Wyoming -- no state income tax.' )
    DC             = ( 'District of Columbia', 'District of Columbia income tax.' )


def _rate( value : str ) -> Rate:
    return Rate( Decimal( value ) )


# The representative effective state income-tax rate for each state -- an approximate share of
# federal AGI for a middle / upper-middle household, not the state's real schedule. The UI's
# auto-fill default; the Profile stores the (possibly overridden) rate the engine actually uses.
_REPRESENTATIVE_RATE : dict[ USState, Rate ] = {
    USState.ALABAMA        : _rate( '0.040' ),
    USState.ALASKA         : _rate( '0.0'   ),
    USState.ARIZONA        : _rate( '0.025' ),
    USState.ARKANSAS       : _rate( '0.035' ),
    USState.CALIFORNIA     : _rate( '0.060' ),
    USState.COLORADO       : _rate( '0.044' ),
    USState.CONNECTICUT    : _rate( '0.050' ),
    USState.DELAWARE       : _rate( '0.050' ),
    USState.FLORIDA        : _rate( '0.0'   ),
    USState.GEORGIA        : _rate( '0.052' ),
    USState.HAWAII         : _rate( '0.070' ),
    USState.IDAHO          : _rate( '0.058' ),
    USState.ILLINOIS       : _rate( '0.0495' ),
    USState.INDIANA        : _rate( '0.030' ),
    USState.IOWA           : _rate( '0.038' ),
    USState.KANSAS         : _rate( '0.053' ),
    USState.KENTUCKY       : _rate( '0.040' ),
    USState.LOUISIANA      : _rate( '0.030' ),
    USState.MAINE          : _rate( '0.060' ),
    USState.MARYLAND       : _rate( '0.050' ),
    USState.MASSACHUSETTS  : _rate( '0.050' ),
    USState.MICHIGAN       : _rate( '0.0425' ),
    USState.MINNESOTA      : _rate( '0.068' ),
    USState.MISSISSIPPI    : _rate( '0.044' ),
    USState.MISSOURI       : _rate( '0.048' ),
    USState.MONTANA        : _rate( '0.059' ),
    USState.NEBRASKA       : _rate( '0.052' ),
    USState.NEVADA         : _rate( '0.0'   ),
    USState.NEW_HAMPSHIRE  : _rate( '0.0'   ),
    USState.NEW_JERSEY     : _rate( '0.050' ),
    USState.NEW_MEXICO     : _rate( '0.047' ),
    USState.NEW_YORK       : _rate( '0.060' ),
    USState.NORTH_CAROLINA : _rate( '0.0425' ),
    USState.NORTH_DAKOTA   : _rate( '0.020' ),
    USState.OHIO           : _rate( '0.035' ),
    USState.OKLAHOMA       : _rate( '0.0475' ),
    USState.OREGON         : _rate( '0.085' ),
    USState.PENNSYLVANIA   : _rate( '0.0307' ),
    USState.RHODE_ISLAND   : _rate( '0.0475' ),
    USState.SOUTH_CAROLINA : _rate( '0.055' ),
    USState.SOUTH_DAKOTA   : _rate( '0.0'   ),
    USState.TENNESSEE      : _rate( '0.0'   ),
    USState.TEXAS          : _rate( '0.0'   ),
    USState.UTAH           : _rate( '0.0455' ),
    USState.VERMONT        : _rate( '0.066' ),
    USState.VIRGINIA       : _rate( '0.0525' ),
    USState.WASHINGTON     : _rate( '0.0'   ),
    USState.WEST_VIRGINIA  : _rate( '0.048' ),
    USState.WISCONSIN      : _rate( '0.053' ),
    USState.WYOMING        : _rate( '0.0'   ),
    USState.DC             : _rate( '0.065' ),
}

# A rate for every state, and no stray keys -- a missing entry is an import-time error, not a
# silent KeyError when the form asks for an auto-fill default.
assert set( _REPRESENTATIVE_RATE ) == set( USState ), \
    'every USState needs exactly one representative rate'


def representative_rate( state : USState ) -> Rate:
    """The representative state income-tax rate to auto-fill for `state` -- the UI's starting
    default, which the user may override on the Profile."""
    return _REPRESENTATIVE_RATE[ state ]
