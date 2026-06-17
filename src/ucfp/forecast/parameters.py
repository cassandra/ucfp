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
from datetime import date
from decimal import Decimal

from ucfp.accounts.enums import AssetClass
from ucfp.tax.engine import TaxContext


@dataclass( frozen = True )
class DateSpan:
    """An inclusive [start_date, end_date] calendar span. A general value object --
    a candidate to relocate to common/ alongside Interval."""

    start_date : date
    end_date   : date


@dataclass( frozen = True )
class AssetRates:
    """Per-AssetClass market rates resolved for one interval: a growth
    (appreciation) rate and a distribution (dividend/interest) rate per class.
    A class absent from a map carries a zero rate."""

    growth       : dict[ AssetClass, Decimal ] = field( default_factory = dict )
    distribution : dict[ AssetClass, Decimal ] = field( default_factory = dict )

    def growth_rate( self, asset_class : AssetClass ) -> Decimal:
        return self.growth.get( asset_class, Decimal( '0' ) )

    def distribution_rate( self, asset_class : AssetClass ) -> Decimal:
        return self.distribution.get( asset_class, Decimal( '0' ) )


class IncomeLine:
    """One income source materializing this interval: the subject, the income
    (tax-treatment) class it credits, and the resolved gross amount.

    NOTE: stub -- fields TBD (needs the income-source / tax-class enums).
    """


class ExpenseLine:
    """One expense materializing this interval: the expense (deductibility) class
    it debits and the resolved amount.

    NOTE: stub -- fields TBD (needs the deductibility enum).
    """


class LiabilityTerm:
    """This interval's terms for one liability: the account, its interest rate, and
    the scheduled payment.

    NOTE: stub -- fields TBD.
    """


class MoneyMovementEvent:
    """A scheduled directive applied this interval (sale, purchase, explicit
    transfer, Roth conversion, RMD) -- shaped much like a Transaction template.

    NOTE: stub -- shape deferred.
    """


class FundingPolicy:
    """How shortfalls are funded: an ordered draw priority across accounts, plus
    conditional movement rules.

    NOTE: stub -- fields TBD.
    """


@dataclass( frozen = True )
class PeriodParameters:
    """The single-interval, already-resolved inputs the Period consumes."""

    date_span             : DateSpan
    tax_context           : TaxContext
    asset_rates           : AssetRates
    funding_policy        : FundingPolicy
    income_lines          : list[ IncomeLine ]         = field( default_factory = list )
    expense_lines         : list[ ExpenseLine ]        = field( default_factory = list )
    liability_terms       : list[ LiabilityTerm ]      = field( default_factory = list )
    money_movement_events : list[ MoneyMovementEvent ] = field( default_factory = list )
