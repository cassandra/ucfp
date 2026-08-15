"""Default Plans policies -- the sensible starting point a plan uses before the user edits it.

`default_drawdown` is the cash-management policy an untouched plan runs with (see the Cash Plan
section): a $25k-$50k band, a liquid-first draw waterfall (retirement last), and no sweep until
targets are chosen. Materialization applies it when `Plans.drawdown` is unset, so every forecast
keeps cash in a sensible band out of the box.
"""
from decimal import Decimal

from ucfp.accounts.enums import AssetClass

from .schemas import DrawdownPolicy

# The liquid asset classes the cash waterfall may sell, in the default priority order (retirement
# last so it is drawn only as a last resort). Physical goods (precious metals, collectibles) and
# illiquid holdings (real estate, vehicles) are excluded -- selling a house or a car to cover a
# small cash dip is not a draw source; cash is the hub itself, not a source. This is also the set
# the Cash Plan draw-order widget offers (shown even when unheld, so the order survives new holdings).
LIQUID_DRAW_CLASSES = (
    AssetClass.CDS,
    AssetClass.BONDS,
    AssetClass.STOCKS,
    AssetClass.DIVIDEND_STOCKS,
    AssetClass.ROTH,
    AssetClass.PRETAX_RETIREMENT,
)

# The classes a cash sweep may invest surplus into: the non-retirement liquid holdings. Retirement
# is excluded (contribution limits, and the engine sweeps at cost basis into taxable holdings). The
# Accounts step keeps a (possibly $0) account for each of these so a sweep always has a home.
SWEEP_TARGET_CLASSES = (
    AssetClass.CDS,
    AssetClass.BONDS,
    AssetClass.STOCKS,
    AssetClass.DIVIDEND_STOCKS,
)

# The stable Accounts handles for the default 50/50 sweep -- the Stocks and Bonds homes, which the
# Accounts step always keeps (at $0 if unfunded), so the default sweep always resolves.
_DEFAULT_SWEEP = [ ( 'stocks', Decimal( '0.5' ) ), ( 'bonds', Decimal( '0.5' ) ) ]


def default_drawdown() -> DrawdownPolicy:
    """The complete cash policy an untouched plan uses: no floor, a $25k ceiling, the liquid draw
    waterfall, and a 50/50 Stocks/Bonds sweep -- since holding too much idle cash is rarely a good plan.
    The floor defaults to zero deliberately: funding then draws from investments (and, worst case, a
    penalized early retirement withdrawal) only to pay a real expense, never merely to top a cash buffer
    back up -- which no rational saver would sell down invested assets to do. The cash-drag reality (some
    wealth sits in low-yield cash) is instead carried by the ceiling: cash accumulates up to it before the
    surplus is swept. A floor remains an available input for anyone who wants a modeled reserve (it matters
    more at fine, near-term granularity). The sweep targets (the Stocks and Bonds accounts) are always
    present, so the ceiling, which the engine requires to come with a sweep destination, is safe to
    default."""
    return DrawdownPolicy(
        cash_floor       = Decimal( '0' ),
        cash_ceiling     = Decimal( '25000' ),
        draw_order       = list( LIQUID_DRAW_CLASSES ),
        sweep_allocation = list( _DEFAULT_SWEEP ) )
