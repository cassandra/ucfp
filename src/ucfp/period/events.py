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
from ucfp.accounts.exceptions import MissingAccountError


class PeriodEvent:
    """Base for a self-applying Period operation; subclasses implement `apply`."""

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        """Post this operation's balanced transaction via `bookkeeper`, with `description` as
        its memo, and return it (None if nothing was posted) -- so a caller can reference the
        transaction, e.g. in a Notice. Events themselves raise no Notices: they are the user's
        requested operations, so they carry a memo, not an attention signal."""
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
            description = description,
        )


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
            description = description,
        )


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
            description = description,
        )


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
            description = description,
        )


@dataclass( frozen = True )
class Realization( PeriodEvent ):
    """Realize `amount` of a holding's market value into a `destination` account,
    recognizing the gain (the valuation portion) into the source asset class's
    realized-gain income class. The destination distinguishes the user-facing meaning:
    the cash hub for a sale or pre-tax withdrawal, or another holding for a conversion
    (e.g. pre-tax -> Roth). Caps at the holding's value. Residence/rental special rules
    (§121, §1250) are not modeled here; a face-value source (cash, CDs) realizes no gain."""

    event_date  : date
    holding     : Account
    amount      : Decimal
    destination : Account

    def apply( self, bookkeeper : Bookkeeper, description : str = '' ) -> Optional[ Transaction ]:
        chart = bookkeeper.chart
        income_class = self.holding.asset_class.realized_gain_income_class
        realized_gain_account = None
        if income_class is not None:
            realized_gain_account = chart.income_account( income_class )
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
            description = description,
        )
