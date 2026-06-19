"""The Period: one step of a Forecast.

A Period is a pure, myopic computation. It takes the Forecast's running books (a
`Bookkeeper`) and this interval's already-resolved `PeriodParameters`, posts the
interval's transactions onto those books, and returns the `Notice`s it raised and the
period's outcome. It does no time math (the Scenario resolves parameters across time) and
treats tax as a pluggable black box (the `TaxEngine` carried on its `PeriodParameters`,
resolved by the Scenario from the tax-law projection).

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
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import SystemAccountRole
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.accounts.money_utils import quantize_money

from .fiscal_window import FiscalWindow
from .parameters import PeriodParameters
from .results import Notice, PeriodResult


class Period:
    """One forecast step over a single interval, computed against a running Bookkeeper."""

    def __init__( self, parameters : PeriodParameters ):
        self._parameters = parameters

    def compute( self, bookkeeper : Bookkeeper ) -> PeriodResult:
        """Post this interval's transactions via `bookkeeper` (the Forecast's running
        books) and return the period's notices and outcome."""
        result = PeriodResult()
        self._accrue( bookkeeper, result )
        self._settle_and_fund( bookkeeper, result )
        self._close( bookkeeper, result )
        return result

    def _accrue( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Everything whose magnitude is known from the opening books and this
        interval's parameters, independent of the funding decision. Sub-steps run
        at their temporal-POV instants (growth at period start; the rest at the
        midpoint)."""
        self._apply_asset_returns( bookkeeper, result )
        self._recognize_income( bookkeeper, result )
        self._service_liabilities( bookkeeper, result )
        self._apply_expenses( bookkeeper, result )
        self._apply_events( bookkeeper, result )
        return

    def _apply_asset_returns( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Per-asset returns for the interval: growth (unrealized appreciation) and
        distributions (dividend/interest income)."""
        self._apply_growth( bookkeeper, result )
        self._apply_distributions( bookkeeper, result )
        return

    def _apply_growth( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Accrue each appreciating holding's unrealized appreciation for the
        interval, on its opening market value (cost + prior valuation), posted at
        period start as DR valuation / CR Unrealized Gains so net worth (= equity)
        stays current."""
        chart = bookkeeper.chart
        ledger = bookkeeper.ledger
        unrealized_gain_account = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
        opening_through = self._parameters.date_span.day_before_start
        growth_date = self._parameters.date_span.start_date
        for holding in chart.holdings():
            if not holding.asset_class.accrues_unrealized_gains:
                continue
            valuation_account = chart.valuation_of( holding )
            if valuation_account is None:
                raise MissingAccountError(
                    f'Appreciating holding "{holding}" has no valuation account.'
                )
            rate = self._parameters.asset_rates.growth_rate( holding.asset_class )
            opening_market = ledger.market_value( holding, through = opening_through )
            appreciation = quantize_money( rate.change_on( opening_market ) )
            if appreciation == 0:
                continue
            if unrealized_gain_account is None:
                raise MissingAccountError( 'No Unrealized Gains equity account for growth.' )
            bookkeeper.record(
                growth_date,
                [ ( valuation_account, -appreciation ), ( unrealized_gain_account, appreciation ) ],
            )
            continue
        return

    def _apply_distributions( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Post each distributing holding's yield (dividend/interest) for the
        interval, at the midpoint: DR the cash hub / CR the income tax-class
        account -- landing the cash in savings and recognizing the income."""
        chart = bookkeeper.chart
        ledger = bookkeeper.ledger
        cash_account = chart.cash_account()
        opening_through = self._parameters.date_span.day_before_start
        distribution_date = self._parameters.date_span.midpoint
        for holding in chart.holdings():
            income_class = holding.asset_class.distribution_income_class
            if income_class is None:
                continue
            rate = self._parameters.asset_rates.distribution_rate( holding.asset_class )
            opening_value = ledger.market_value( holding, through = opening_through )
            distribution = quantize_money( rate.change_on( opening_value ) )
            if distribution == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to receive distributions.' )
            income_account = chart.income_account( income_class )
            if income_account is None:
                raise MissingAccountError(
                    f'No revenue account for income tax-class {income_class.label}.'
                )
            bookkeeper.record(
                distribution_date,
                [ ( cash_account, -distribution ), ( income_account, distribution ) ],
            )
            continue
        return

    def _recognize_income( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Post the resolved `income_lines` (salary/pension/SS) at the midpoint:
        DR the cash hub / CR each line's revenue account. Lines name their account
        directly, so per-worker wage accounts (which share the WAGES class) post
        unambiguously."""
        cash_account = bookkeeper.chart.cash_account()
        income_date = self._parameters.date_span.midpoint
        for income_line in self._parameters.income_lines:
            amount = quantize_money( income_line.gross_amount )
            if amount == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to receive income.' )
            bookkeeper.record(
                income_date,
                [ ( cash_account, -amount ), ( income_line.account, amount ) ],
            )
            continue
        return

    def _service_liabilities( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Apply each loan's payment for the interval, at the midpoint: interest to
        its interest expense account, scheduled + extra principal to the loan, all
        from the cash hub. The Scenario resolves the breakdown; cash shortfalls are
        the funding step's concern, not here."""
        cash_account = bookkeeper.chart.cash_account()
        payment_date = self._parameters.date_span.midpoint
        for term in self._parameters.liability_terms:
            interest = quantize_money( term.interest )
            total_principal = quantize_money( term.principal ) + quantize_money( term.extra_principal )
            payment = total_principal + interest
            if payment == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to pay liabilities from.' )
            bookkeeper.record(
                payment_date,
                [
                    ( term.liability_account, -total_principal ),
                    ( term.interest_account, -interest ),
                    ( cash_account, payment ),
                ],
            )
            continue
        return

    def _apply_expenses( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Post the resolved `expense_lines` at the midpoint: DR each line's expense
        account / CR the cash hub. Lines name their account directly, so per-item expense
        accounts (sharing a tax-class) post unambiguously."""
        cash_account = bookkeeper.chart.cash_account()
        expense_date = self._parameters.date_span.midpoint
        for expense_line in self._parameters.expense_lines:
            amount = quantize_money( expense_line.amount )
            if amount == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to pay expenses from.' )
            bookkeeper.record(
                expense_date,
                [ ( expense_line.account, -amount ), ( cash_account, amount ) ],
            )
            continue
        return

    def _apply_events( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Apply each scheduled PeriodEvent (transfer, purchase, sale, conversion);
        each materializes its own balanced transaction(s)."""
        for event in self._parameters.events:
            result.notices.extend( event.apply( bookkeeper ) )
            continue
        return

    def _settle_and_fund( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Fund cash up to the policy's target buffer first -- so the draws' realized
        income is taxed this period -- then settle the period's tax on the full
        income. Tax may pull cash below the target (even negative); that balance is
        carried into the next period as a visible cash-flow signal, and only a net
        worth at or below zero ends the forecast (see _close). Because all funding
        precedes settlement, no untaxed income is ever carried -- only cash is."""
        self._fund_to_target( bookkeeper, result )
        self._settle_tax( bookkeeper, result )
        return

    def _settle_tax( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Assess the tax year and book each charge as a tax expense drawn from the cash
        hub. (The zero-tax engine yields none.)

        Tax is annual, so settlement is gated to the year-close interval: the Scenario sets
        `tax_engine` (and the paired `fiscal_window`) only there, so a non-settling interval
        carries no engine and this returns immediately. When present, the engine assesses
        over `fiscal_window` (the full tax year, Jan-Dec), not the interval's own slice, so
        a December month's window still sees the whole year's flows.

        The engine's opening tax state (carryforwards) is threaded in, and its closing
        state captured on the result -- even in a no-charge year, since a capital-loss year
        produces a carryover with no tax due.

        Charges are paid (DR tax expense / CR cash); refundable credits are the reverse
        (CR the tax expense / DR cash), so a credit beyond the matching tax leaves a net
        refund -- modeled here as a negated charge against the same expense class."""
        if self._parameters.tax_engine is None:
            return
        fiscal_window = FiscalWindow( bookkeeper, self._parameters.fiscal_window )
        assessment = self._parameters.tax_engine.assess(
            fiscal_window, self._parameters.tax_context, self._parameters.opening_tax_state )
        result.closing_tax_state = assessment.closing_tax_state
        settlements = (
            [ ( charge.tax_class, charge.amount ) for charge in assessment.charges ]
            + [ ( credit.tax_class, -credit.amount ) for credit in assessment.credits ] )
        if not settlements:
            return
        chart = bookkeeper.chart
        cash_account = chart.cash_account()
        settle_date = self._parameters.date_span.end_date
        for expense_class, amount in settlements:
            amount = quantize_money( amount )
            if amount == 0:
                continue
            if cash_account is None:
                raise MissingAccountError( 'No cash account to pay tax from.' )
            expense_account = chart.expense_account( expense_class )
            if expense_account is None:
                raise MissingAccountError(
                    f'No expense account for expense tax-class {expense_class.label}.'
                )
            bookkeeper.record(
                settle_date,
                [ ( expense_account, -amount ), ( cash_account, amount ) ],
            )
            continue
        return

    def _fund_to_target( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Draw from the funding policy's accounts in priority order (realizing
        gains as it goes) until cash reaches the policy's cash_target, or the
        sources are exhausted. Dated at the period start so the draw precedes the
        expenses it funds. A single pre-settlement pass: every gain it realizes is
        taxed this period, so nothing is carried but the ending cash balance."""
        chart = bookkeeper.chart
        ledger = bookkeeper.ledger
        cash_account = chart.cash_account()
        if cash_account is None:
            return
        target = self._parameters.funding_policy.cash_target
        fund_date = self._parameters.date_span.start_date
        for source in self._parameters.funding_policy.draw_priority:
            shortfall = target - ledger.natural_balance( cash_account )
            if shortfall <= 0:
                break
            available = ledger.market_value( source )
            draw = quantize_money( min( shortfall, available ) )
            if draw <= 0:
                continue
            income_class = None
            if source.asset_class is not None:
                income_class = source.asset_class.realized_gain_income_class
            realized_gain_account = None
            if income_class is not None:
                realized_gain_account = chart.income_account( income_class )
                if realized_gain_account is None:
                    raise MissingAccountError(
                        f'No revenue account for income tax-class {income_class.label}.'
                    )
            bookkeeper.realize(
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

    def _close( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Finalize the period: flag the stop condition when net worth is depleted
        (assets no longer cover liabilities), which ends the Forecast."""
        if bookkeeper.ledger.net_worth() <= 0:
            result.is_depleted = True
            result.notices.append( Notice( 'Net worth depleted; the forecast should stop.' ) )
        return
