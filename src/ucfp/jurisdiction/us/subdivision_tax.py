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
from typing import Optional

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


def _exempt( social_security : str, retirement : str ) -> tuple[ Decimal, Decimal ]:
    return ( Decimal( social_security ), Decimal( retirement ) )


# The share of retirement income each state exempts from its base, as ( Social Security, pension +
# withdrawals ) fractions -- 0 fully taxes it, 1 fully exempts it. COARSE approximations for a middle /
# upper-middle 2026 retiree, NOT the state's real rules (many use age or income thresholds, fixed-dollar
# exclusions, or public-vs-private distinctions this flattens to a single fraction). The dominant signal:
# most states exempt Social Security, and a few (IL, PA, MS, IA) exempt pensions and withdrawals broadly.
# Plain data -- adjust a number here. No-income-tax states carry (1, 1); it is moot (their rate is 0).
_RETIREMENT_EXEMPTION : dict[ USState, tuple[ Decimal, Decimal ] ] = {
    USState.ALABAMA        : _exempt( '1.0', '0.5' ),   # exempts defined-benefit pensions, taxes IRA/401k
    USState.ALASKA         : _exempt( '1.0', '1.0' ),   # no income tax
    USState.ARIZONA        : _exempt( '1.0', '0.0' ),
    USState.ARKANSAS       : _exempt( '1.0', '0.0' ),   # only a small ($6k) exclusion
    USState.CALIFORNIA     : _exempt( '1.0', '0.0' ),   # taxes all retirement income except SS
    USState.COLORADO       : _exempt( '1.0', '0.5' ),   # 65+ retirement-income deduction (capped)
    USState.CONNECTICUT    : _exempt( '0.5', '0.5' ),   # income-based SS + phasing-in pension exemption
    USState.DELAWARE       : _exempt( '1.0', '0.5' ),   # ~$12.5k exclusion at 60+
    USState.FLORIDA        : _exempt( '1.0', '1.0' ),   # no income tax
    USState.GEORGIA        : _exempt( '1.0', '1.0' ),   # $65k exclusion at 65+ covers most middle retirees
    USState.HAWAII         : _exempt( '1.0', '0.5' ),   # exempts employer pensions, taxes IRA/401k
    USState.IDAHO          : _exempt( '1.0', '0.0' ),
    USState.ILLINOIS       : _exempt( '1.0', '1.0' ),   # fully exempts retirement income
    USState.INDIANA        : _exempt( '1.0', '0.0' ),
    USState.IOWA           : _exempt( '1.0', '1.0' ),   # 55+ retirement income exempt (2023+)
    USState.KANSAS         : _exempt( '1.0', '0.5' ),   # SS exempt; taxes retirement (public pension out)
    USState.KENTUCKY       : _exempt( '1.0', '0.5' ),   # ~$31k retirement exclusion
    USState.LOUISIANA      : _exempt( '1.0', '0.5' ),   # small private exclusion, full public pension
    USState.MAINE          : _exempt( '1.0', '0.5' ),   # ~$45k pension exclusion
    USState.MARYLAND       : _exempt( '1.0', '0.5' ),   # ~$39k pension exclusion at 65+
    USState.MASSACHUSETTS  : _exempt( '1.0', '0.5' ),   # exempts govt pensions, taxes private/IRA
    USState.MICHIGAN       : _exempt( '1.0', '0.5' ),   # phasing the retirement exemption back in
    USState.MINNESOTA      : _exempt( '0.5', '0.0' ),   # partial SS subtraction, taxes retirement
    USState.MISSISSIPPI    : _exempt( '1.0', '1.0' ),   # fully exempts qualified retirement income
    USState.MISSOURI       : _exempt( '1.0', '0.5' ),   # SS exempt; public pension + income-based private
    USState.MONTANA        : _exempt( '0.5', '0.0' ),
    USState.NEBRASKA       : _exempt( '1.0', '0.0' ),   # SS exempt; taxes retirement income
    USState.NEVADA         : _exempt( '1.0', '1.0' ),   # no income tax
    USState.NEW_HAMPSHIRE  : _exempt( '1.0', '1.0' ),   # no tax on wage/retirement income
    USState.NEW_JERSEY     : _exempt( '1.0', '0.5' ),   # generous but income-capped exclusion
    USState.NEW_MEXICO     : _exempt( '0.5', '0.0' ),   # income-based SS exemption
    USState.NEW_YORK       : _exempt( '1.0', '0.5' ),   # full govt pension + $20k private/IRA at 59.5+
    USState.NORTH_CAROLINA : _exempt( '1.0', '0.0' ),   # taxes retirement (Bailey exempts certain govt)
    USState.NORTH_DAKOTA   : _exempt( '1.0', '0.0' ),   # SS exempt; taxes retirement
    USState.OHIO           : _exempt( '1.0', '0.0' ),   # only a small retirement credit
    USState.OKLAHOMA       : _exempt( '1.0', '0.5' ),   # $10k exclusion, full for some
    USState.OREGON         : _exempt( '1.0', '0.0' ),   # only a small credit
    USState.PENNSYLVANIA   : _exempt( '1.0', '1.0' ),   # fully exempts retirement income after retirement
    USState.RHODE_ISLAND   : _exempt( '0.5', '0.0' ),   # income-based
    USState.SOUTH_CAROLINA : _exempt( '1.0', '0.5' ),   # $10k retirement + $15k age deduction
    USState.SOUTH_DAKOTA   : _exempt( '1.0', '1.0' ),   # no income tax
    USState.TENNESSEE      : _exempt( '1.0', '1.0' ),   # no income tax
    USState.TEXAS          : _exempt( '1.0', '1.0' ),   # no income tax
    USState.UTAH           : _exempt( '0.5', '0.0' ),   # income-based retirement credit
    USState.VERMONT        : _exempt( '0.5', '0.0' ),   # taxes retirement income
    USState.VIRGINIA       : _exempt( '1.0', '0.5' ),   # $12k age deduction at 65+
    USState.WASHINGTON     : _exempt( '1.0', '1.0' ),   # no tax on ordinary income
    USState.WEST_VIRGINIA  : _exempt( '1.0', '0.5' ),   # SS fully exempt by 2026; partial retirement
    USState.WISCONSIN      : _exempt( '1.0', '0.0' ),   # only a small low-income exclusion
    USState.WYOMING        : _exempt( '1.0', '1.0' ),   # no income tax
    USState.DC             : _exempt( '1.0', '0.0' ),   # taxes retirement income
}

# One exemption pair for every state, and no stray keys -- a missing entry is an import-time error.
assert set( _RETIREMENT_EXEMPTION ) == set( USState ), \
    'every USState needs exactly one retirement-exemption entry'


def state_tax_policy( state : Optional[ USState ], rate : Rate ) -> StateIncomeTax:
    """The state income-tax policy for a household: the (overridable) `rate` combined with `state`'s
    retirement-income exemptions. No state ("Other / not listed") is the flat rate with no exemptions."""
    if state is None:
        return StateIncomeTax( rate = rate )
    social_security_exempt, retirement_exempt = _RETIREMENT_EXEMPTION[ state ]
    return StateIncomeTax( rate = rate, social_security_exempt = social_security_exempt,
                           retirement_exempt = retirement_exempt )
