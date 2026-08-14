"""Estimated Future Taxes -- the latent tax embedded in account values, booked as a liability so that
net worth reflects realizable (after-tax) wealth rather than the gross balance.

Two kinds of value carry tax the household has not yet paid: a pre-tax retirement balance is taxable in
full at ordinary rates when withdrawn, and a taxable investment account carries an unrealized gain taxed
at capital-gains rates when realized. This module classifies each holding, estimates that tax at
assumed rates, and re-estimates the `Estimated Future Taxes` liability to the current total each time it
is called. The re-estimate is an idempotent to-target sweep: because it recomputes from *current*
balances, the liability shrinks on its own as an account is drawn down and its real tax is booked at
realization -- so the estimate self-corrects and never double-counts. Rates default to zero, which
targets zero and books nothing, leaving the books identical to a run without the feature.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from common.rate import Rate, ZERO_RATE
from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass, SystemAccountRole
from ucfp.accounts.ledger import Ledger
from ucfp.accounts.money_utils import quantize_money

_ESTIMATED_FUTURE_TAX_MEMO = 'Estimated future tax re-estimate'

# Which realized-gain income classes the estimate taxes, and at which assumed rate. This is a feature
# policy, deliberately narrower than `AssetClass.realized_gain_income_class`: a primary residence (§121
# exclusion) and precious metals / collectibles have realized-gain classes but are excluded from the
# estimate, so they are simply absent here and fall through to a zero rate.
_ORDINARY_LATENT_CLASSES      = frozenset( { IncomeTaxClass.RETIREMENT_DISTRIBUTION } )
_CAPITAL_GAINS_LATENT_CLASSES = frozenset( {
    IncomeTaxClass.LONG_TERM_GAINS, IncomeTaxClass.RENTAL_SALE_GAIN, IncomeTaxClass.SECOND_HOME_GAIN } )


def future_tax_rate( asset_class : AssetClass, ordinary_rate : Rate, capital_gains_rate : Rate ) -> Rate:
    """The assumed rate the estimate applies to `asset_class`: the ordinary rate for pre-tax retirement
    (the whole balance is taxable), the capital-gains rate for taxable investments carrying unrealized
    gains (stocks, bonds, second home, rental), and zero for everything the estimate excludes -- Roth,
    cash, CDs, primary residence, precious metals, collectibles, and depreciating assets."""
    realized_class = asset_class.realized_gain_income_class
    if realized_class in _ORDINARY_LATENT_CLASSES:
        return ordinary_rate
    if realized_class in _CAPITAL_GAINS_LATENT_CLASSES:
        return capital_gains_rate
    return ZERO_RATE


def estimated_future_tax(
        holding : Account, ledger : Ledger, ordinary_rate : Rate, capital_gains_rate : Rate,
        *, through : Optional[ date ] = None ) -> Decimal:
    """The estimated future tax embedded in `holding`: its taxable amount -- market value less cost
    basis, which is the whole balance for a zero-basis pre-tax account and the unrealized gain for a
    taxable account -- times the assumed rate for its class. Floored at zero: an unrealized loss carries
    no tax benefit here, since the estimate is a liability owed, not a speculative credit against gains
    the household may never have to offset."""
    rate = future_tax_rate( holding.asset_class, ordinary_rate, capital_gains_rate )
    if rate.fraction == 0:
        return Decimal( '0' )
    taxable = ( ledger.market_value( holding, through = through )
                - ledger.natural_balance( holding, through = through ) )
    if taxable <= 0:
        return Decimal( '0' )
    return quantize_money( taxable * rate.fraction )


def reestimate_future_taxes(
        bookkeeper : Bookkeeper, ordinary_rate : Rate, capital_gains_rate : Rate, on_date : date ) -> None:
    """Move the `Estimated Future Taxes` liability to the total estimated tax across all holdings,
    booking the delta from its current balance dated `on_date` (credit the liability / debit its
    Deferred Tax Reserve equity counterpart, so net worth falls by the liability). Idempotent to-target:
    called at t0 and again at each period close, it always reconciles the liability to what current
    balances imply, so a drawn-down account releases its share on its own and the real tax booked at
    realization is never double-counted. A zero target against a zero balance books nothing, so zero
    rates leave the books untouched."""
    chart  = bookkeeper.chart
    ledger = bookkeeper.ledger
    target = sum(   # each per-holding estimate is already money-quantized; the booked delta re-quantizes
        ( estimated_future_tax( holding, ledger, ordinary_rate, capital_gains_rate, through = on_date )
          for holding in chart.holdings() ),
        Decimal( '0' ) )
    liability = chart.system_account( SystemAccountRole.ESTIMATED_FUTURE_TAXES )
    reserve   = chart.system_account( SystemAccountRole.DEFERRED_TAX_RESERVE )
    current   = ledger.natural_balance( liability, through = on_date )
    delta     = quantize_money( target - current )
    if delta == 0:
        return
    bookkeeper.record(
        on_date, [ ( liability, delta ), ( reserve, -delta ) ],
        description = _ESTIMATED_FUTURE_TAX_MEMO )
    return
