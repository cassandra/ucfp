"""Self-applying Period operations (events).

A `PeriodEvent` is a scheduled operation the Period materializes into balanced
transactions during the Accrue phase -- a `Transfer`, `Purchase`, `Sale`, or
`Conversion`. Each is a frozen dataclass that applies itself, so adding a new kind of
operation is one new subclass. The Scenario constructs these (and materializes derived
ones -- e.g. an RMD as a pre-tax `Sale`). "Money-movement event" is the user-facing term;
`PeriodEvent` is the engine-internal type.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper

from .exceptions import MissingAccountError, ProjectionError
from .results import Notice


class PeriodEvent:
    """Base for a self-applying Period operation; subclasses implement `apply`."""

    def apply( self, bookkeeper : Bookkeeper ) -> list[ Notice ]:
        """Post this operation's balanced transaction(s) via `bookkeeper`, returning any
        Notices it raises."""
        raise NotImplementedError


@dataclass( frozen = True )
class Transfer( PeriodEvent ):
    """Move value between two asset accounts, with no tax effect (e.g. cash -> CD)."""

    event_date     : date
    source_account : Account
    target_account : Account
    amount         : Decimal

    def apply( self, bookkeeper : Bookkeeper ) -> list[ Notice ]:
        bookkeeper.record(
            self.event_date,
            [ ( self.target_account, -self.amount ), ( self.source_account, self.amount ) ],
        )
        return []


@dataclass( frozen = True )
class Purchase( PeriodEvent ):
    """Acquire an asset at cost, funded from a cash account: the asset account
    gains the cost (its basis); the funding account is drawn down."""

    event_date      : date
    funding_account : Account
    asset_account   : Account
    amount          : Decimal

    def apply( self, bookkeeper : Bookkeeper ) -> list[ Notice ]:
        bookkeeper.record(
            self.event_date,
            [ ( self.asset_account, -self.amount ), ( self.funding_account, self.amount ) ],
        )
        return []


@dataclass( frozen = True )
class Sale( PeriodEvent ):
    """Sell `amount` of a holding's market value to the cash hub, realizing the
    gain into the asset class's realized-gain income class (caps at the holding's
    value). Residence/rental special rules (§121, §1250) are not yet applied."""

    event_date : date
    holding    : Account
    amount     : Decimal

    def apply( self, bookkeeper : Bookkeeper ) -> list[ Notice ]:
        income_class = self.holding.asset_class.realized_gain_income_class
        if income_class is None:
            raise ProjectionError(
                f'Sale of {self.holding.asset_class.label} is not supported '
                '(no realized-gain income class).'
            )
        chart = bookkeeper.chart
        cash = chart.cash_account()
        if cash is None:
            raise MissingAccountError( 'No cash account to receive sale proceeds.' )
        realized_gain_account = chart.income_account( income_class )
        if realized_gain_account is None:
            raise MissingAccountError(
                f'No revenue account for income tax-class {income_class.label}.'
            )
        bookkeeper.realize(
            self.holding,
            self.amount,
            proceeds_account = cash,
            realized_gain_account = realized_gain_account,
            on_date = self.event_date,
        )
        return []


@dataclass( frozen = True )
class Conversion( PeriodEvent ):
    """Convert pre-tax retirement to Roth: recognize ordinary income on the amount,
    moving the value into the Roth holding rather than to cash.

    NOTE: stub -- pending the conversion realization primitive.
    """

    def apply( self, bookkeeper : Bookkeeper ) -> list[ Notice ]:
        raise NotImplementedError
