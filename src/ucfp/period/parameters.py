"""Inputs to a single Period computation.

`PeriodParameters` is the myopic, single-interval slice the Scenario resolves from
its `EconomicAssumptions` + `PersonalParameters` + subjects (rates compounded to
the interval, inflation/COLA applied, ages resolved). The Period consumes these as
already-resolved values and does no time math itself. It is a shallow composite of
cohesive value objects, all constructed by the Scenario.

NOTE: only `DateSpan` and the composite are grounded; the remaining sub-types are
stubs whose intended fields are sketched in their docstrings, to be grounded one
at a time (each needs enums not yet built). See
data/design/projection-model.md, "PeriodParameters".
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from common.rate import Rate, ZERO_RATE
from ucfp.accounts.books import Account
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.tax.engine import TaxEngine, ZeroTaxEngine
from ucfp.tax.us.context import TaxContext

from .events import PeriodEvent


@dataclass( frozen = True )
class DateSpan:
    """An inclusive [start_date, end_date] calendar span. A general value object --
    a candidate to relocate to common/ alongside Interval."""

    start_date : date
    end_date   : date

    @property
    def day_before_start( self ) -> date:
        """The day immediately before the span -- the point through which opening
        balances are read (the prior period's close)."""
        return self.start_date - timedelta( days = 1 )

    @property
    def midpoint( self ) -> date:
        """The span's midpoint date; events default here (the mid-period convention)."""
        return self.start_date + timedelta( days = ( self.end_date - self.start_date ).days // 2 )


@dataclass( frozen = True )
class AssetRates:
    """Per-AssetClass market rates resolved for one interval: a growth
    (appreciation) rate and a distribution (dividend/interest) rate per class.
    A class absent from a map carries a zero rate."""

    growth       : dict[ AssetClass, Rate ] = field( default_factory = dict )
    distribution : dict[ AssetClass, Rate ] = field( default_factory = dict )

    def growth_rate( self, asset_class : AssetClass ) -> Rate:
        return self.growth.get( asset_class, ZERO_RATE )

    def distribution_rate( self, asset_class : AssetClass ) -> Rate:
        return self.distribution.get( asset_class, ZERO_RATE )


@dataclass( frozen = True )
class IncomeLine:
    """One income source materializing this interval: the revenue account it credits
    and the resolved gross amount. The account carries the income tax-class and -- for
    wages -- identifies the worker, since each worker has their own WAGES account (the
    per-worker Social Security cap treats them separately). Lines name the account
    directly so multiple accounts of one class (per-worker wages) post unambiguously;
    distributions and realized gains, which are one account per class, are posted by
    class elsewhere.
    """

    account      : Account
    gross_amount : Decimal


@dataclass( frozen = True )
class ExpenseLine:
    """One class of expense materializing this interval: the expense tax-class it
    debits and the resolved amount (the Scenario aggregates the user's detailed
    per-item expenses into per-class lines)."""

    expense_tax_class : ExpenseTaxClass
    amount            : Decimal


@dataclass( frozen = True )
class LiabilityTerm:
    """This interval's payment for one loan (loans are modeled individually).

    The Scenario owns the amortization schedule and resolves the breakdown
    directly, so the Period just posts it -- no rate or opening-balance math here.
    Scheduled `principal` and `extra_principal` are kept separate (an extra payment
    is worth surfacing); both reduce the loan. `interest_account` is the expense
    account the interest is booked to; it carries the deductibility class the tax
    engine reads, so the class lives on the account, not here.
    """

    liability_account : Account
    interest_account  : Account
    principal         : Decimal
    interest          : Decimal
    extra_principal   : Decimal = Decimal( '0' )


@dataclass( frozen = True )
class FundingPolicy:
    """How a savings shortfall is funded: a target cash balance to maintain and an
    ordered list of accounts to draw from. The waterfall draws from each in turn
    (realizing gains) until cash reaches `cash_target` or the sources are exhausted.
    Tax settled afterward can pull cash below the target -- even negative -- and
    that balance simply carries into the next period as a visible cash-flow signal;
    only a net worth at or below zero ends the forecast.

    `cash_target` is resolved per interval by the Scenario, so the user-facing
    policy can be absolute, a multiple of expenses, or inflation-adjusted upstream.
    """

    cash_target   : Decimal = Decimal( '0' )
    draw_priority : list[ Account ] = field( default_factory = list )


@dataclass( frozen = True )
class PeriodParameters:
    """The single-interval, already-resolved inputs the Period consumes.

    `tax_engine` is the resolved tax strategy for this interval and `opening_tax_state`
    its carryforwards entering the interval -- both resolved by the Scenario (the engine
    from the tax-law projection, the state threaded from the prior period) and consumed
    here exactly like the other resolved inputs. `tax_engine` defaults to the no-tax
    engine so a standalone Period needs no tax wiring."""

    date_span             : DateSpan
    tax_context           : TaxContext
    asset_rates           : AssetRates
    funding_policy        : FundingPolicy
    income_lines          : list[ IncomeLine ]         = field( default_factory = list )
    expense_lines         : list[ ExpenseLine ]        = field( default_factory = list )
    liability_terms       : list[ LiabilityTerm ]      = field( default_factory = list )
    events                : list[ PeriodEvent ]        = field( default_factory = list )
    tax_engine            : TaxEngine                  = field( default_factory = ZeroTaxEngine )
    opening_tax_state     : object                     = None
