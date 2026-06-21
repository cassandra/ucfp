"""Required minimum distributions (RMDs) for pre-tax retirement accounts (US).

A standalone `tax/us` helper the Scenario calls to size the forced withdrawal each year
once the owner reaches the RMD age; the Period then executes the withdrawal through the
existing draw mechanism (and the engine taxes it as ordinary income). Roth accounts have
no lifetime RMDs, so the Scenario applies this only to pre-tax holdings.

The first-year April-1 required-beginning-date delay is not modeled.
"""
from decimal import Decimal

# IRS Uniform Lifetime Table (2022+): age -> distribution-period factor. The required
# distribution is the prior year-end balance divided by the factor. Ages past the table
# use the final (120+) factor.
_UNIFORM_LIFETIME_TABLE = {
    73 : Decimal( '26.5' ), 74 : Decimal( '25.5' ), 75 : Decimal( '24.6' ),
    76 : Decimal( '23.7' ), 77 : Decimal( '22.9' ), 78 : Decimal( '22.0' ),
    79 : Decimal( '21.1' ), 80 : Decimal( '20.2' ), 81 : Decimal( '19.4' ),
    82 : Decimal( '18.5' ), 83 : Decimal( '17.7' ), 84 : Decimal( '16.8' ),
    85 : Decimal( '16.0' ), 86 : Decimal( '15.2' ), 87 : Decimal( '14.4' ),
    88 : Decimal( '13.7' ), 89 : Decimal( '12.9' ), 90 : Decimal( '12.2' ),
    91 : Decimal( '11.5' ), 92 : Decimal( '10.8' ), 93 : Decimal( '10.1' ),
    94 : Decimal( '9.5' ), 95 : Decimal( '8.9' ), 96 : Decimal( '8.4' ),
    97 : Decimal( '7.8' ), 98 : Decimal( '7.3' ), 99 : Decimal( '6.8' ),
    100 : Decimal( '6.4' ), 101 : Decimal( '6.0' ), 102 : Decimal( '5.6' ),
    103 : Decimal( '5.2' ), 104 : Decimal( '4.9' ), 105 : Decimal( '4.6' ),
    106 : Decimal( '4.3' ), 107 : Decimal( '4.1' ), 108 : Decimal( '3.9' ),
    109 : Decimal( '3.7' ), 110 : Decimal( '3.5' ), 111 : Decimal( '3.4' ),
    112 : Decimal( '3.3' ), 113 : Decimal( '3.1' ), 114 : Decimal( '3.0' ),
    115 : Decimal( '2.9' ), 116 : Decimal( '2.8' ), 117 : Decimal( '2.7' ),
    118 : Decimal( '2.5' ), 119 : Decimal( '2.3' ), 120 : Decimal( '2.0' ),
}
_MAX_TABLE_AGE = 120


def rmd_start_age( birth_year : int ) -> int:
    """The age at which RMDs begin, by SECURE 2.0 birth cohort: 72 for those born
    through 1950, 73 for 1951-1959, and 75 for 1960 and later."""
    if birth_year <= 1950:
        return 72
    if birth_year <= 1959:
        return 73
    return 75


def required_minimum_distribution(
        account_balance : Decimal, age : int, birth_year : int ) -> Decimal:
    """The RMD for a pre-tax retirement account: the prior year-end `account_balance`
    divided by the Uniform Lifetime Table factor for `age`. Zero before the owner's
    cohort RMD age. Ages past the table use the 120+ factor."""
    if age < rmd_start_age( birth_year ):
        return Decimal( '0' )
    factor = _UNIFORM_LIFETIME_TABLE[ min( age, _MAX_TABLE_AGE ) ]
    return account_balance / factor
