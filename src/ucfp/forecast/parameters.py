"""`ForecastParameters`: the full materialized data a Forecast needs to run N steps.

The N-step analog of `PeriodParameters` -- one container of cohesive sub-objects, in
*materialized* form (the upstream materialization layer builds it from frictionless UX
intent; profiles, ladders, and segment timelines are expanded away by then).

There is no separate "Baseline" input: the opening books are encoded in the asset (and
later liability) parameters' opening values, and the Forecast creates the chart and
ledger from them. A "Scenario" is a *variation* of a ForecastParameters -- the
comparison/what-if layer above the engine -- and is not modelled here.

STUB: subjects + assets + frame + filing status + the tax-forecast profile + the
cash-target knob. Income, Expenses, Liabilities, Events, and the Economic Outlook join
incrementally; per-item value-rules and existence windows ride on the item sub-objects.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from ucfp.accounts.enums import AssetClass
from ucfp.period.parameters import DateSpan
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus


def _add_years( anchor : date, years : int ) -> date:
    """`anchor` advanced by whole years (Feb 29 -> Feb 28 in a non-leap target year)."""
    try:
        return anchor.replace( year = anchor.year + years )
    except ValueError:
        return anchor.replace( year = anchor.year + years, day = 28 )


@dataclass
class Subject:
    """A person on the forecast -- the invariant kernel; age is derived per interval."""

    birthdate : date


@dataclass
class AssetParameters:
    """A holding: its opening value and asset class. The Forecast creates the holding
    account from this and seeds the opening value. STUB: `opening_value` is the basis
    (= market at t0, no embedded unrealized gain); a basis/market split and the
    value-rule + existence window join later."""

    name          : str
    asset_class   : AssetClass
    opening_value : Decimal


@dataclass
class ForecastParameters:
    """The full materialized inputs for an N-step Forecast (see module docstring)."""

    start_date        : date
    end_date          : date
    filing_status     : FilingStatus
    tax_forecast      : TaxForecastProfile
    label             : str                     = ''
    subjects          : list[ Subject ]         = field( default_factory = list )
    assets            : list[ AssetParameters ] = field( default_factory = list )
    cash_target       : Decimal                 = Decimal( '0' )
    initial_tax_state : object                  = None

    def period_spans( self ) -> list[ DateSpan ]:
        """The horizon sliced into consecutive one-year intervals (the last truncated to
        `end_date`). Granularity is yearly for now -- it matches the annual tax engine."""
        spans  = list()
        cursor = self.start_date
        while cursor <= self.end_date:
            following = _add_years( cursor, 1 )
            spans.append( DateSpan( cursor, min( following - timedelta( days = 1 ), self.end_date ) ) )
            cursor = following
            continue
        return spans
