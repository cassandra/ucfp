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
from ucfp.accounts.enums import AssetClass
from ucfp.tax.engine import TaxEngine
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

    def over_fraction( self, fraction : Decimal ) -> 'AssetRates':
        """These annual rates rescaled to `fraction` of a year, for a sub-annual interval:
        growth compounds (geometric), distributions prorate (linear) -- each translation
        reconciling back over a full year. `fraction == 1` returns self unchanged."""
        if fraction == 1:
            return self
        return AssetRates(
            growth       = { cls : rate.compounded( fraction ) for cls, rate in self.growth.items() },
            distribution = { cls : rate.prorated( fraction ) for cls, rate in self.distribution.items() },
        )


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
    """One expense materializing this interval: the expense account it debits and the
    resolved amount. Like `IncomeLine`, lines name the account directly, so per-item
    expense accounts (which share an expense tax-class) post unambiguously while the tax
    engine still aggregates by class."""

    account : Account
    amount  : Decimal


@dataclass( frozen = True )
class ContributionLine:
    """One retirement contribution materializing this interval: it debits the target holding's
    `valuation_account` (the zero-basis representation, so the whole amount is taxed on a later
    withdrawal) and credits its `funding_account` -- the cash hub for an employee contribution
    (net-worth-neutral) or the External Receipts equity for an employer match (net-worth-
    increasing). `description` is the posting memo. The Scenario resolves the accounts and the
    grown amount; the Period just posts it."""

    valuation_account : Account
    funding_account   : Account
    amount            : Decimal
    description       : str = ''


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

    `tax_engine` is the year's resolved engine (from the tax-law projection), carried every
    interval. Tax is annual, so the Period asks the engine whether the interval's end closes
    a tax year and settles only then, over the full tax-year span the engine names (Jan-Dec)
    -- so the boundary is the tax law's to decide, not a pre-set window's presence. A `None`
    engine simply runs no tax step. `opening_tax_state` is the carryforwards threaded in from
    the prior period."""

    date_span             : DateSpan
    tax_context           : TaxContext
    asset_rates           : AssetRates
    funding_policy        : FundingPolicy
    income_lines          : list[ IncomeLine ]         = field( default_factory = list )
    expense_lines         : list[ ExpenseLine ]        = field( default_factory = list )
    liability_terms       : list[ LiabilityTerm ]      = field( default_factory = list )
    contribution_lines    : list[ ContributionLine ]   = field( default_factory = list )
    events                : list[ PeriodEvent ]        = field( default_factory = list )
    tax_engine            : TaxEngine                  = None
    opening_tax_state     : object                     = None
