"""The Forecast: the N-step engine above the Period.

Parallels the Period one level up -- `ForecastParameters -> Forecast -> ForecastResult`,
as `PeriodParameters -> Period -> PeriodResult`. The Forecast materializes the chart and
opening books from the asset/liability parameters (the "baseline" is encoded there, not
handed in), then walks the frame: resolve each interval's `PeriodParameters`, run the
`Period` on the running Ledger, apply feedback knobs, thread `TaxState`, accumulate, and
stop at the horizon or net-worth depletion.

Boundary (the running-state test): the Forecast owns only what needs the running
projection state -- per-period resolution that depends on the books, the feedback knobs,
state threading. Projection-independent expansion (profiles, ladders, segment timelines)
is upstream materialization that builds the `ForecastParameters`.

It selects the tax law via the parameters' `TaxForecastProfile` and treats the resulting
engine as a black box: it asks the `TaxLaw` for each year's engine and never touches a
tax knob.

STUB: per-period resolution is minimal (subjects -> tax_context; empty rates/lines/
events; funding from the cash-target). The WHAT categories and the feedback knobs
(funding draws, RMDs, adaptive conversions) join incrementally.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from ucfp.accounts.enums import AccountType, SystemAccountRole
from ucfp.accounts.ledger import Ledger
from ucfp.accounts.models import Account
from ucfp.period import chart
from ucfp.period.parameters import AssetRates, DateSpan, FundingPolicy, PeriodParameters
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult
from ucfp.tax.law import TaxLaw
from ucfp.tax.us.context import TaxContext, TaxSubject

from .parameters import ForecastParameters


@dataclass
class ForecastStep:
    """One interval's outcome within a run: its span, the Period's result, and the net
    worth at the interval's end. (Further per-step snapshots can join later.)"""

    span      : DateSpan
    result    : PeriodResult
    net_worth : Decimal


@dataclass
class ForecastResult:
    """What a Forecast run produces: each interval's step, and whether it stopped early
    (net-worth depletion before the horizon)."""

    steps         : list[ ForecastStep ] = field( default_factory = list )
    stopped_early : bool = False


class Forecast:
    """Runs a `ForecastParameters` to completion (N Period steps); see the module
    docstring for the boundary."""

    def __init__( self, organization, parameters : ForecastParameters ):
        self._organization = organization
        self._parameters   = parameters
        self._tax_law      = TaxLaw( parameters.tax_forecast )

    def run( self ) -> ForecastResult:
        """Build the opening books from the parameters, then walk the frame running a
        Period per interval -- threading the tax state and stopping at depletion."""
        ledger        = self._build_baseline()
        result        = ForecastResult()
        opening_state = self._parameters.initial_tax_state
        for span in self._parameters.period_spans():
            period_parameters = self._build_period_parameters( span, opening_state )
            period            = Period( period_parameters )
            period_result     = period.compute( ledger )
            ending_net_worth  = chart.net_worth( ledger, through = span.end_date )
            result.steps.append( ForecastStep( span, period_result, ending_net_worth ) )
            if period_result.closing_tax_state is not None:
                opening_state = period_result.closing_tax_state
            if period_result.is_depleted:
                result.stopped_early = True
                break
            continue
        return result

    def _build_baseline( self ) -> Ledger:
        """Create the chart and opening books from the asset parameters -- the baseline is
        encoded in the parameters, not handed in. Holdings are created first so the Ledger
        snapshots them; one opening transaction seeds each holding's value against Opening
        Balances. STUB: holdings only; liabilities join later."""
        Account.objects.initialize_chart( self._organization )
        asset_root = self._organization.accounts.get(
            parent = None, account_type = AccountType.ASSET )
        holdings = [
            ( Account.objects.create_holding(
                organization = self._organization, parent = asset_root,
                name = asset.name, asset_class = asset.asset_class ), asset.opening_value )
            for asset in self._parameters.assets ]
        ledger        = Ledger.empty( self._organization )
        opening_total = sum( ( value for _holding, value in holdings ), Decimal( '0' ) )
        if opening_total != 0:
            opening_balances = chart.system_account( ledger, SystemAccountRole.OPENING_BALANCES )
            postings = [ ( holding, -value ) for holding, value in holdings ]
            postings.append( ( opening_balances, opening_total ) )
            ledger.record( self._parameters.start_date - timedelta( days = 1 ), postings )
        return ledger

    def _build_period_parameters( self, span : DateSpan, opening_tax_state ) -> PeriodParameters:
        """Build this interval's myopic PeriodParameters, injecting the year's tax engine
        (from the tax-law projection) and the threaded carryforwards. STUB: tax_context
        from subjects; empty rates/lines/events; funding from the cash-target."""
        return PeriodParameters(
            date_span         = span,
            tax_context       = self._tax_context_for( span ),
            asset_rates       = AssetRates(),
            funding_policy    = FundingPolicy( cash_target = self._parameters.cash_target ),
            tax_engine        = self._tax_law.engine_for( span.end_date.year ),
            opening_tax_state = opening_tax_state,
        )

    def _tax_context_for( self, span : DateSpan ) -> TaxContext:
        """The taxpayer context for the interval: ages from birthdates at the interval's
        end. STUB: filing status static; properties/ACA not yet resolved."""
        subjects = tuple(
            TaxSubject( age = span.end_date.year - subject.birthdate.year )
            for subject in self._parameters.subjects )
        return TaxContext( filing_status = self._parameters.filing_status, subjects = subjects )
