"""Self-applying Period operations (events).

A `PeriodEvent` is a scheduled operation the Period materializes into balanced
transactions during the Accrue phase -- a `Transfer`, `Purchase`, or `Realization`. Each
is a frozen dataclass that applies itself, so adding a new kind of operation is one new
subclass. The Forecast resolves the user's scheduled events (which name holdings) into
these (which hold accounts), and materializes derived ones -- e.g. an RMD as a pre-tax
`Realization` to cash. "Money-movement event" is the user-facing term; `PeriodEvent` is
the engine-internal type.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from ucfp.accounts.books import Account, Transaction
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.accounts.money_utils import quantize_money


class PeriodEvent:
    """Base for a self-applying Period operation; subclasses implement `apply`."""

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        """Post this operation's balanced transaction via `bookkeeper`, with `description` as
        its memo, and return it (None if nothing was posted) -- so a caller can reference the
        transaction, e.g. in a Notice. Events themselves raise no Notices: they are the user's
        requested operations, so they carry a memo, not an attention signal. When the caller
        supplies no memo, each event falls back to a self-describing one (`_describe`) built from
        the accounts it touches, so a scheduled operation still reads meaningfully in the drill-down."""
        raise NotImplementedError


@dataclass( frozen = True )
class Transfer( PeriodEvent ):
    """Move value between two asset accounts, with no tax effect (e.g. cash -> CD)."""

    event_date     : date
    source_account : Account
    target_account : Account
    amount         : Decimal

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        return bookkeeper.record(
            self.event_date,
            [ ( self.target_account, -self.amount ), ( self.source_account, self.amount ) ],
            description = description or self._describe(),
        )

    def _describe( self ) -> str:
        return f'Transfer from {self.source_account.name} to {self.target_account.name}'


@dataclass( frozen = True )
class ExternalReceipt( PeriodEvent ):
    """Non-taxable value received from outside landing in cash -- a gift or a US inheritance
    (non-taxable to the recipient, the estate tax being the estate's). The cash account is debited
    and the External Receipts `equity_account` credited; the tax engine never sees it. Taxable
    one-time income (a lottery win, a settlement) is an `IncomeItem` with a `OneTime` cadence, not
    this event."""

    event_date     : date
    cash_account   : Account
    equity_account : Account
    amount         : Decimal

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        return bookkeeper.record(
            self.event_date,
            [ ( self.cash_account, -self.amount ), ( self.equity_account, self.amount ) ],
            description = description or self._describe(),
        )

    def _describe( self ) -> str:
        return f'Gift or inheritance received into {self.cash_account.name}'


@dataclass( frozen = True )
class ExternalDisbursement( PeriodEvent ):
    """Non-deductible value given away to outside, leaving cash -- a personal gift to family, say.
    The mirror of `ExternalReceipt`: the cash account is credited and the External Disbursements
    `equity_account` debited, so net worth drops by the amount with no expense recognized. A
    deductible charitable gift is an expense (`ExpenseTaxClass.CHARITABLE`), not this event."""

    event_date     : date
    cash_account   : Account
    equity_account : Account
    amount         : Decimal

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        return bookkeeper.record(
            self.event_date,
            [ ( self.cash_account, self.amount ), ( self.equity_account, -self.amount ) ],
            description = description or self._describe(),
        )

    def _describe( self ) -> str:
        return f'Personal gift given from {self.cash_account.name}'


@dataclass( frozen = True )
class LoanPayoff( PeriodEvent ):
    """Extinguish a loan's remaining balance at a date, funded from cash: the whole balance still
    owed is taken off the liability and drawn from the cash hub, zeroing the loan so no further
    amortization posts. The balance is read live from the ledger at apply time -- the projected
    amount the engine knows, not a planner-supplied figure -- so a payoff dated after the loan has
    already been retired posts nothing. Mirrors the principal half of a liability service payment,
    with the full remaining balance and no interest. The balance is quantized to cents: a loan already
    retired -- or amortized down to a sub-cent residual (the quantized payments never sum exactly to the
    opening balance) -- rounds to zero and posts nothing, so no zero-magnitude entry can reach the books."""

    event_date        : date
    liability_account : Account
    cash_account      : Account

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        balance = quantize_money( bookkeeper.ledger.natural_balance( self.liability_account ) )
        if balance <= 0:
            return None
        return bookkeeper.record(
            self.event_date,
            [ ( self.liability_account, -balance ), ( self.cash_account, balance ) ],
            description = description or self._describe(),
        )

    def _describe( self ) -> str:
        return f'Payoff of {self.liability_account.name}'


@dataclass( frozen = True )
class LoanOrigination( PeriodEvent ):
    """Originate a loan mid-forecast: credit its `principal` to the liability and land the proceeds
    in cash, the balance-sheet mirror of `LoanPayoff`. From here the loan carries a real balance the
    Forecast amortizes (its level payment was derived from this same principal at build), so a
    recurring purchase can finance each replacement with a fresh loan. The borrow balances on its own
    -- liability up, cash up -- with no equity plug (unlike the t0 opening seed, which is booked
    against Opening Balances). A non-positive principal posts nothing.

    A loan paid off in the same span it originates inherits the engine's existing payoff simplification:
    liabilities are serviced before events, so that span's amortized interest is granularity-sensitive
    (it reflects payments through the span end, then the payoff clears the balance). The final balance is
    correct at any granularity; only the interest split within a settle-in-one-span cycle drifts."""

    event_date        : date
    liability_account : Account
    cash_account      : Account
    principal         : Decimal

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        if self.principal <= 0:
            return None
        return bookkeeper.record(
            self.event_date,
            [ ( self.liability_account, self.principal ), ( self.cash_account, -self.principal ) ],
            description = description or self._describe(),
        )

    def _describe( self ) -> str:
        return f'Origination of {self.liability_account.name}'


@dataclass( frozen = True )
class Purchase( PeriodEvent ):
    """Acquire an asset at cost, funded from a cash account: the asset account
    gains the cost (its basis); the funding account is drawn down."""

    event_date      : date
    funding_account : Account
    asset_account   : Account
    amount          : Decimal

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        return bookkeeper.record(
            self.event_date,
            [ ( self.asset_account, -self.amount ), ( self.funding_account, self.amount ) ],
            description = description or self._describe(),
        )

    def _describe( self ) -> str:
        return f'Purchase of {self.asset_account.name} funded from {self.funding_account.name}'


@dataclass( frozen = True )
class Realization( PeriodEvent ):
    """Realize `amount` of a holding's market value into a `destination` account,
    recognizing the gain (the valuation portion) into the source asset class's
    realized-gain income class. The destination distinguishes the user-facing meaning:
    the cash hub for a sale or pre-tax withdrawal, or another holding for a conversion
    (e.g. pre-tax -> Roth). `amount` of None realizes the entire holding (a full sale);
    otherwise it caps at the holding's value. Residence/rental special rules (§121, §1250)
    are not modeled here; a face-value source (cash, CDs) realizes no gain."""

    event_date  : date
    holding     : Account
    amount      : Optional[ Decimal ]
    destination : Account

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        chart = bookkeeper.chart
        income_class = self.holding.asset_class.realized_gain_income_class
        realized_gain_account = None
        if income_class is not None:
            # Owner-attributed income (a retirement distribution) posts to the account owner's own
            # revenue account; household income (a capital gain) to the single shared one.
            owner_handle = self.holding.owner_handle if income_class.is_owner_attributed else None
            realized_gain_account = chart.income_account( income_class, owner_handle )
            if realized_gain_account is None:
                raise MissingAccountError(
                    f'No revenue account for income tax-class {income_class.label}.'
                )
        return bookkeeper.realize(
            self.holding,
            self.amount,
            proceeds_account = self.destination,
            realized_gain_account = realized_gain_account,
            on_date = self.event_date,
            basis_first = self.holding.asset_class.withdraws_basis_first,
            description = description or self._describe(),
        )

    def _describe( self ) -> str:
        """A default memo naming the operation from the accounts involved: a conversion when the proceeds
        go to another holding, a withdrawal when a retirement holding is drawn to cash, else a plain sale.
        Used only when the caller supplies no memo -- a derived RMD passes its own reason instead."""
        if self.destination.asset_class != AssetClass.CASH:
            return f'Conversion of {self.holding.name} to {self.destination.name}'
        if self.holding.asset_class in ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH ):
            return f'Withdrawal from {self.holding.name}'
        return f'Sale of {self.holding.name}'


@dataclass( frozen = True )
class PropertySale( PeriodEvent ):
    """A whole-property sale as a thin trigger: the `holding` to sell, the date, and whether the household
    rents after (the residence choice; a non-residence sale ignores it). Unlike the other events it does
    not apply itself -- the Period dispatches it to the shared property-sale routine, which reaches the
    property's `PropertyData` for the mortgage payoff and reports the sale for the forecast's expense
    reconfiguration. Holding only these three fields (no realize/payoff machinery) keeps a scheduled sale
    and a shortfall-driven one identical downstream; `apply` is deliberately left to raise, since a sale
    reaching it unrouted is a wiring error."""

    event_date : date
    holding    : Account
    rent_after : bool
