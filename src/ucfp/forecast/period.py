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

NOTE: Phase-1 complete against the zero-tax engine. The USFederalTaxEngine and the
Conversion event are the remaining pieces.
"""
from ucfp.accounts.enums import SystemAccountRole
from ucfp.accounts.ledger import Ledger
from ucfp.accounts.money_utils import quantize_money
from ucfp.tax.engine import TaxEngine

from . import chart
from .exceptions import MissingAccountError
from .fiscal_window import FiscalWindow
from .parameters import PeriodParameters
from .results import Notice, PeriodResult


class Period:
    """One forecast step over a single interval, computed against a running Ledger."""

    def __init__( self,
                  parameters       : PeriodParameters,
                  tax_engine       : TaxEngine,
                  opening_tax_state = None ):
        self._parameters        = parameters
        self._tax_engine        = tax_engine
        self._opening_tax_state = opening_tax_state

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
        """Accrue each appreciating holding's unrealized appreciation for the
        interval, on its opening market value (cost + prior valuation), posted at
        period start as DR valuation / CR Unrealized Gains so net worth (= equity)
        stays current."""
        unrealized_gain_account = chart.system_account( ledger, SystemAccountRole.UNREALIZED_GAINS )
        opening_through = self._parameters.date_span.day_before_start
        growth_date = self._parameters.date_span.start_date
        for holding in chart.holdings( ledger ):
            if not holding.asset_class.accrues_unrealized_gains:
                continue
            valuation_account = chart.valuation_of( ledger, holding )
            if valuation_account is None:
                raise MissingAccountError(
                    f'Appreciating holding "{holding}" has no valuation account.'
                )
            rate = self._parameters.asset_rates.growth_rate( holding.asset_class )
            opening_market = chart.market_value( ledger, holding, through = opening_through )
            appreciation = quantize_money( rate.change_on( opening_market ) )
            if appreciation == 0:
                continue
            if unrealized_gain_account is None:
                raise MissingAccountError( 'No Unrealized Gains equity account for growth.' )
            ledger.record(
                growth_date,
                valuation_account.currency,
                [ ( valuation_account, -appreciation ), ( unrealized_gain_account, appreciation ) ],
            )
            continue
        return

    def _apply_distributions( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Post each distributing holding's yield (dividend/interest) for the
        interval, at the midpoint: DR the cash hub / CR the income tax-class
        account -- landing the cash in savings and recognizing the income."""
        cash_account = chart.cash_account( ledger )
        opening_through = self._parameters.date_span.day_before_start
        distribution_date = self._parameters.date_span.midpoint
        for holding in chart.holdings( ledger ):
            income_class = holding.asset_class.distribution_income_class
            if income_class is None:
                continue
            rate = self._parameters.asset_rates.distribution_rate( holding.asset_class )
            opening_value = chart.market_value( ledger, holding, through = opening_through )
            distribution = quantize_money( rate.change_on( opening_value ) )
            if distribution == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to receive distributions.' )
            income_account = chart.income_account( ledger, income_class )
            if income_account is None:
                raise MissingAccountError(
                    f'No revenue account for income tax-class {income_class.label}.'
                )
            ledger.record(
                distribution_date,
                cash_account.currency,
                [ ( cash_account, -distribution ), ( income_account, distribution ) ],
            )
            continue
        return

    def _recognize_income( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Post the resolved `income_lines` (salary/pension/SS) at the midpoint:
        DR the cash hub / CR each line's revenue account. Lines name their account
        directly, so per-worker wage accounts (which share the WAGES class) post
        unambiguously."""
        cash_account = chart.cash_account( ledger )
        income_date = self._parameters.date_span.midpoint
        for income_line in self._parameters.income_lines:
            amount = quantize_money( income_line.gross_amount )
            if amount == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to receive income.' )
            ledger.record(
                income_date,
                cash_account.currency,
                [ ( cash_account, -amount ), ( income_line.account, amount ) ],
            )
            continue
        return

    def _service_liabilities( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Apply each loan's payment for the interval, at the midpoint: interest to
        its interest expense account, scheduled + extra principal to the loan, all
        from the cash hub. The Scenario resolves the breakdown; cash shortfalls are
        the funding step's concern, not here."""
        cash_account = chart.cash_account( ledger )
        payment_date = self._parameters.date_span.midpoint
        for term in self._parameters.liability_terms:
            interest = quantize_money( term.interest )
            total_principal = quantize_money( term.principal ) + quantize_money( term.extra_principal )
            payment = total_principal + interest
            if payment == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to pay liabilities from.' )
            ledger.record(
                payment_date,
                cash_account.currency,
                [
                    ( term.liability_account, -total_principal ),
                    ( term.interest_account, -interest ),
                    ( cash_account, payment ),
                ],
            )
            continue
        return

    def _apply_expenses( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Post the resolved per-class `expense_lines` at the midpoint: DR the
        expense tax-class account / CR the cash hub."""
        cash_account = chart.cash_account( ledger )
        expense_date = self._parameters.date_span.midpoint
        for expense_line in self._parameters.expense_lines:
            amount = quantize_money( expense_line.amount )
            if amount == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to pay expenses from.' )
            expense_account = chart.expense_account( ledger, expense_line.expense_tax_class )
            if expense_account is None:
                raise MissingAccountError(
                    f'No expense account for expense tax-class {expense_line.expense_tax_class.label}.'
                )
            ledger.record(
                expense_date,
                cash_account.currency,
                [ ( expense_account, -amount ), ( cash_account, amount ) ],
            )
            continue
        return

    def _apply_events( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Apply each scheduled PeriodEvent (transfer, purchase, sale, conversion);
        each materializes its own balanced transaction(s)."""
        for event in self._parameters.events:
            result.notices.extend( event.apply( ledger ) )
            continue
        return

    def _settle_and_fund( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Fund cash up to the policy's target buffer first -- so the draws' realized
        income is taxed this period -- then settle the period's tax on the full
        income. Tax may pull cash below the target (even negative); that balance is
        carried into the next period as a visible cash-flow signal, and only a net
        worth at or below zero ends the forecast (see _close). Because all funding
        precedes settlement, no untaxed income is ever carried -- only cash is."""
        self._fund_to_target( ledger, result )
        self._settle_tax( ledger, result )
        return

    def _settle_tax( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Assess the period's tax via the pluggable engine and book each charge as
        a tax expense drawn from the cash hub. (The zero-tax engine yields none.)

        The engine assesses against a fiscal-year `FiscalWindow`, not the period's
        own slice -- income tax is an annual computation. For an annual period the
        window is the period's span; once the Scenario drives sub-annual cadences it
        will gate settlement to the year-close period and supply the full-year span.

        The engine's opening tax state (carryforwards) is threaded in, and its
        closing state captured on the result -- even in a no-charge year, since a
        capital-loss year produces a carryover with no tax due."""
        fiscal_window = FiscalWindow( ledger, self._parameters.date_span )
        assessment = self._tax_engine.assess(
            fiscal_window, self._parameters.tax_context, self._opening_tax_state )
        result.closing_tax_state = assessment.closing_tax_state
        if not assessment.charges:
            return
        cash_account = chart.cash_account( ledger )
        settle_date = self._parameters.date_span.end_date
        for expense_class, amount in assessment.charges:
            amount = quantize_money( amount )
            if amount == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to pay tax from.' )
            expense_account = chart.expense_account( ledger, expense_class )
            if expense_account is None:
                raise MissingAccountError(
                    f'No expense account for expense tax-class {expense_class.label}.'
                )
            ledger.record(
                settle_date,
                cash_account.currency,
                [ ( expense_account, -amount ), ( cash_account, amount ) ],
            )
            continue
        return

    def _fund_to_target( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Draw from the funding policy's accounts in priority order (realizing
        gains as it goes) until cash reaches the policy's cash_target, or the
        sources are exhausted. Dated at the period start so the draw precedes the
        expenses it funds. A single pre-settlement pass: every gain it realizes is
        taxed this period, so nothing is carried but the ending cash balance."""
        cash_account = chart.cash_account( ledger )
        if cash_account is None:
            return
        target = self._parameters.funding_policy.cash_target
        fund_date = self._parameters.date_span.start_date
        for source in self._parameters.funding_policy.draw_priority:
            shortfall = target - ledger.natural_balance( cash_account )
            if shortfall <= 0:
                break
            available = chart.market_value( ledger, source )
            draw = quantize_money( min( shortfall, available ) )
            if draw <= 0:
                continue
            income_class = None
            if source.asset_class is not None:
                income_class = source.asset_class.realized_gain_income_class
            realized_gain_account = None
            if income_class is not None:
                realized_gain_account = chart.income_account( ledger, income_class )
                if realized_gain_account is None:
                    raise MissingAccountError(
                        f'No revenue account for income tax-class {income_class.label}.'
                    )
            chart.realize(
                ledger,
                source,
                draw,
                proceeds_account = cash_account,
                realized_gain_account = realized_gain_account,
                on_date = fund_date,
            )
            result.notices.append(
                Notice( f'Drew {draw} from "{source}" to cover a savings shortfall.' )
            )
            continue
        return

    def _close( self, ledger : Ledger, result : PeriodResult ) -> None:
        """Finalize the period: flag the stop condition when net worth is depleted
        (assets no longer cover liabilities), which ends the Forecast."""
        if chart.net_worth( ledger ) <= 0:
            result.is_depleted = True
            result.notices.append( Notice( 'Net worth depleted; the forecast should stop.' ) )
        return
