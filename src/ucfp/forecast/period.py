"""The Period: one step of a Forecast.

A Period is a pure, myopic computation. It takes the Forecast's running books (a
`Ledger`) and this interval's already-resolved `PeriodParameters`, posts the
interval's transactions onto those books, and returns the `Notice`s it raised and
the period's outcome. It does no time math (the Scenario resolves parameters
across time) and treats tax as a pluggable black box (`TaxEngine`), which the
Scenario constructs once and passes to each Period.

The interval is computed in three phases (see data/design/projection-model.md):
  1. Accrue        -- effects whose magnitude is known up front: asset growth and
                      distributions, income, liability service, scheduled expenses
                      and money-movement events, each at its temporal-POV instant.
  2. Settle & fund -- assess tax for the period, then cover any shortfall via the
                      funding waterfall (with a heuristic gross-up). The only phase
                      with the tax/draw circular dependency.
  3. Close         -- finalize ending balances and the stop condition.

NOTE: top-level orchestration stub. Phase bodies (and the collaborator shapes they
use) are deliberately unimplemented pending design refinement.
"""
from datetime import timedelta

from ucfp.accounts.enums import SystemAccountRole
from ucfp.accounts.ledger import Ledger
from ucfp.accounts.money_utils import quantize_money
from ucfp.tax.engine import TaxEngine

from .parameters import PeriodParameters
from .results import PeriodResult


class Period:
    """One forecast step over a single interval, computed against a running Ledger."""

    def __init__( self, parameters : PeriodParameters, tax_engine : TaxEngine ):
        self._parameters = parameters
        self._tax_engine = tax_engine

    def compute( self, ledger : Ledger ) -> PeriodResult:
        """Post this interval's transactions onto `ledger` (the Forecast's running
        books) and return the period's notices and outcome."""
        result = PeriodResult()
        self._accrue( ledger, result )
        self._settle_and_fund( ledger, result )
        self._close( ledger, result )
        return result

    def _accrue( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Everything whose magnitude is known from the opening books and this
        interval's parameters, independent of the funding decision. Sub-steps run
        at their temporal-POV instants (growth at period start; the rest at the
        midpoint)."""
        self._apply_asset_returns( ledger, result )
        self._recognize_income( ledger, result )
        self._service_liabilities( ledger, result )
        self._apply_expenses( ledger, result )
        self._apply_events( ledger, result )
        return

    def _apply_asset_returns( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Per-asset returns for the interval: growth (unrealized appreciation) and
        distributions (dividend/interest income)."""
        self._apply_growth( ledger, result )
        self._apply_distributions( ledger, result )
        return

    def _apply_growth( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Accrue each holding's unrealized appreciation for the interval, on its
        opening market value (cost + prior valuation), posted at period start as
        DR valuation / CR Unrealized Gains so net worth (= equity) stays current."""
        unrealized_gain_account = ledger.system_account( SystemAccountRole.UNREALIZED_GAINS )
        opening_through = self._parameters.date_span.start_date - timedelta( days = 1 )
        growth_date = self._parameters.date_span.start_date
        for holding in ledger.holdings():
            valuation_account = ledger.valuation_of( holding )
            if valuation_account is None:
                continue
            rate = self._parameters.asset_rates.growth_rate( holding.asset_class )
            opening_market = (
                ledger.natural_balance( holding, through = opening_through )
                + ledger.natural_balance( valuation_account, through = opening_through )
            )
            appreciation = quantize_money( rate.change_on( opening_market ) )
            if appreciation == 0:
                continue
            ledger.record(
                growth_date,
                valuation_account.currency,
                [ ( valuation_account, -appreciation ), ( unrealized_gain_account, appreciation ) ],
            )
            continue
        return

    def _apply_distributions( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Distributions (dividend/interest) -> Savings + the income tax-class.

        NOTE: stub -- grounded after the income tax-class taxonomy + CASH routing.
        """
        raise NotImplementedError

    def _recognize_income( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Post the resolved `income_lines` (salary/pension/SS/rental) -> Savings,
        crediting each line's income tax-class revenue account, at the midpoint."""
        raise NotImplementedError

    def _service_liabilities( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Apply each `liability_terms` scheduled payment: Savings -> principal
        (reducing the liability) plus interest (an expense, deductible or not)."""
        raise NotImplementedError

    def _apply_expenses( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Post the resolved `expense_lines` -> expense accounts, drawn from
        Savings, at the midpoint."""
        raise NotImplementedError

    def _apply_events( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Apply the scheduled `money_movement_events` (sales, purchases, explicit
        transfers, Roth conversions, RMDs), each at its event date; some realize
        gains or generate taxable income and may raise a Notice."""
        raise NotImplementedError

    def _settle_and_fund( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Assess tax for the period, then fund any shortfall via the waterfall
        (heuristic gross-up). The phase carrying the tax/draw circularity."""
        raise NotImplementedError

    def _close( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Finalize ending balances and the stop condition (e.g. savings <= 0)."""
        raise NotImplementedError
