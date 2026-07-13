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


def default_drawdown() -> DrawdownPolicy:
    """The cash policy an untouched plan uses: a $25k floor and the liquid draw waterfall. No ceiling
    or sweep yet -- the engine requires a ceiling to come with a sweep allocation (a destination to
    invest the surplus into), so the maximum and the sweep are set together in the sweep step; until
    then, surplus simply stays in cash."""
    return DrawdownPolicy(
        cash_floor       = Decimal( '25000' ),
        cash_ceiling     = None,
        draw_order       = list( LIQUID_DRAW_CLASSES ),
        sweep_allocation = [] )
