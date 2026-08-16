"""Inputs to a single Period computation.

`PeriodParameters` is the myopic, single-interval slice the Scenario resolves from
its `EconomicAssumptions` + `PersonalParameters` + subjects (rates compounded to
the interval, inflation/COLA applied, ages resolved). The Period consumes these as
already-resolved values and does no time math itself. It is a shallow composite of
cohesive value objects, all constructed by the Scenario.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from common.date_span import DateSpan
from common.rate import Rate, ZERO_RATE
from ucfp.accounts.books import Account
from ucfp.accounts.enums import AssetClass
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.engine import ContributionKind, TaxEngine, TaxState

from .events import PeriodEvent
from .fiscal_window import FiscalWindow


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
    class elsewhere. `source` is the income's own label (the flow's name), carried so the
    posting memo can tell apart several sources that share one (subject, class) account --
    two jobs, say; None when the source has no distinct label.
    """

    account      : Account
    gross_amount : Decimal
    source       : Optional[ str ] = None


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
    """One retirement contribution materializing this interval into the target `holding`: the
    Period debits the holding's zero-basis valuation companion (so the whole amount is taxed on a
    later withdrawal) and credits its `funding_account` -- the cash hub for an employee
    contribution (net-worth-neutral) or the External Receipts equity for an employer match
    (net-worth-increasing). `description` is the posting memo. The Scenario resolves the holding,
    funding account, and grown amount; the Period posts it after the annual-limit clamp.

    `holding`'s `owner_handle` plus `kind` group contributions that share one annual limit, which
    the Period clamps each group's year-to-date total to. An employer match counts against no
    employee limit, so its `kind` is None (never clamped)."""

    holding         : Account
    funding_account : Account
    amount          : Decimal
    kind            : Optional[ ContributionKind ] = None
    description     : str = ''


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
    """How the cash hub is kept within its band. Below `cash_floor`, the waterfall draws
    (realizing gains) from `draw_priority` in turn until cash reaches the floor or the sources
    are exhausted. Above `cash_ceiling` (when set), the surplus is swept across `sweep_allocation`
    as investments at cost. Tax settled afterward can pull cash below the floor -- even
    negative -- and that balance carries into the next period as a visible cash-flow signal;
    only a net worth at or below zero ends the forecast.

    The bounds are resolved per interval by the Scenario, so the user-facing policy can be
    absolute, a multiple of expenses, or inflation-adjusted upstream.
    """

    cash_floor       : Decimal = Decimal( '0' )
    draw_priority    : list[ Account ] = field( default_factory = list )
    cash_ceiling     : Optional[ Decimal ] = None
    sweep_allocation : tuple[ tuple[ Account, Decimal ], ... ] = ()   # resolved ( holding Account, weight ) pairs for the sweep
    secured_loans    : dict[ str, tuple[ str, ... ] ] = field( default_factory = dict )   # property handle -> its mortgage account handles


@dataclass( frozen = True )
class PeriodParameters:
    """The single-interval, already-resolved inputs the Period consumes.

    `tax_engine` is the year's resolved engine (from the tax-law projection), carried every
    interval so its exact, non-bracket rules -- the retirement contribution limit, the
    early-withdrawal penalty, forced RMDs -- apply to every year. Income tax, by contrast, is
    annual and bracket-driven, so it settles only when the interval closes a *full* calendar year:
    the Period settles when `_is_close_of_tax_year()` and `full_tax_year`. `full_tax_year` is
    False for a partial year (a mid-year start, or a trailing year short of December 31), which is
    posted but not income-taxed -- the Forecast decides fullness; the boundary is the tax law's.
    `opening_tax_state` is the carryforwards threaded in from the prior period. `fiscal_window` is
    the tax-year view the Forecast resolves for this interval -- the year-to-date window the Period
    reads for the contribution clamp and the year-close tax step."""

    date_span             : DateSpan
    tax_context           : TaxContext
    asset_rates           : AssetRates
    funding_policy        : FundingPolicy
    income_lines          : list[ IncomeLine ]                              = field( default_factory = list )
    expense_lines         : list[ ExpenseLine ]                             = field( default_factory = list )
    liability_terms       : list[ LiabilityTerm ]                           = field( default_factory = list )
    contribution_lines    : list[ ContributionLine ]                        = field( default_factory = list )
    events                : list[ PeriodEvent ]                             = field( default_factory = list )
    tax_engine            : Optional[ TaxEngine ]                           = None
    full_tax_year         : bool                                           = True
    opening_tax_state     : Optional[ TaxState ]                            = None
    fiscal_window         : Optional[ FiscalWindow ]                        = None
    # Selling costs applied to a property sale this interval: a realtor rate on the sale price plus a
    # fixed cost already inflated to this year (the Forecast inflates it, like other today's-dollar
    # inputs). Carried as primitives so this myopic slice needs no engine-parameters import.
    property_sale_realtor_fee_rate : Rate    = ZERO_RATE
    property_sale_fixed_cost        : Decimal = Decimal( '0' )
    # The rates the Estimated Future Taxes overlay applies at each close: ordinary on pre-tax retirement
    # balances, capital-gains on unrealized investment gains. Zero (the default) books no overlay.
    latent_ordinary_tax_rate      : Rate = ZERO_RATE
    latent_capital_gains_tax_rate : Rate = ZERO_RATE
