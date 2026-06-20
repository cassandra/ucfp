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

NOTE: Phase-1 complete against the zero-tax engine. The Forecast resolves scheduled
events (Transfer/Purchase/Realization) into each period's parameters.
"""
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import SystemAccountRole
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.accounts.money_utils import quantize_money

from .events import Realization
from .fiscal_window import FiscalWindow
from .parameters import DateSpan, PeriodParameters
from .results import Notice, NoticeKind, NoticeSeverity, PeriodResult


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
        self._apply_contributions( bookkeeper, result )
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

    def _apply_contributions( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Post the resolved retirement `contribution_lines` at the midpoint (after income, so
        cash is present): DR the holding's valuation companion / CR its funding account -- cash
        for an employee contribution (net-worth-neutral), External Receipts equity for an
        employer match (net-worth-increasing). Requested inputs, so they carry a memo, not a
        Notice."""
        contribution_date = self._parameters.date_span.midpoint
        for line in self._parameters.contribution_lines:
            amount = quantize_money( line.amount )
            if amount == 0:
                continue
            bookkeeper.record(
                contribution_date,
                [ ( line.valuation_account, -amount ), ( line.funding_account, amount ) ],
                description = line.description,
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
        """Apply each scheduled PeriodEvent (transfer, purchase, realization, windfall); each
        materializes its own balanced transaction. Scheduled events are the user's requested
        operations, so they raise no Notices (a Notice flags the unrequested)."""
        for event in self._parameters.events:
            event.apply( bookkeeper )
            continue
        return

    def _settle_and_fund( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Fund cash up to the policy's target buffer first -- so the draws' realized
        income is taxed this period -- then settle the period's tax on the full
        income. Tax may pull cash below the target (even negative); that balance is
        carried into the next period as a visible cash-flow signal, and only a net
        worth at or below zero ends the forecast (see _close). Because all funding
        precedes settlement, no untaxed income is ever carried -- only cash is."""
        self._check_forced_tax_transactions( bookkeeper, result )
        self._fund_to_target( bookkeeper, result )
        self._assess_penalties( bookkeeper, result )
        self._settle_tax( bookkeeper, result )
        return

    def _fiscal_window( self, bookkeeper : Bookkeeper ):
        """The tax-year window to act on if this interval closes a tax year, else None. The
        engine -- carried every interval -- names the boundary, so settlement, the penalty,
        and forced transactions all act only at that close, over the full year (Jan-Dec, not
        the interval's own slice)."""
        tax_engine = self._parameters.tax_engine
        period_end = self._parameters.date_span.end_date
        if ( tax_engine is None ) or ( not tax_engine.closes_tax_year( period_end ) ):
            return None
        start_date, end_date = tax_engine.tax_year_bounds( period_end )
        return FiscalWindow( bookkeeper, DateSpan( start_date, end_date ) )

    def _settle_tax( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Assess the tax year and book each charge as a tax expense drawn from the cash hub.
        (The zero-tax engine yields none.) Settlement runs only at the tax-year close.

        The engine's opening tax state (carryforwards) is threaded in, and its closing
        state captured on the result -- even in a no-charge year, since a capital-loss year
        produces a carryover with no tax due.

        Charges are paid (DR tax expense / CR cash); refundable credits are the reverse
        (CR the tax expense / DR cash), so a credit beyond the matching tax leaves a net
        refund -- modeled here as a negated charge against the same expense class."""
        fiscal_window = self._fiscal_window( bookkeeper )
        if fiscal_window is None:
            return
        assessment = self._parameters.tax_engine.assess(
            fiscal_window, self._parameters.tax_context, self._parameters.opening_tax_state )
        result.closing_tax_state = assessment.closing_tax_state
        settlements = (
            [ ( charge.tax_class, charge.amount ) for charge in assessment.charges ]
            + [ ( credit.tax_class, -credit.amount ) for credit in assessment.credits ] )
        self._book_charges( bookkeeper, settlements, self._parameters.date_span.end_date )
        return

    def _book_charges( self, bookkeeper : Bookkeeper, settlements : list, settle_date ) -> None:
        """Book each `(expense tax-class, amount)` as a tax expense drawn from the cash hub."""
        for expense_class, amount in settlements:
            self._book_charge( bookkeeper, expense_class, amount, settle_date )
            continue
        return

    def _book_charge( self, bookkeeper : Bookkeeper, expense_class, amount, settle_date,
                      description : str = '' ):
        """Book one `expense_class` charge as a tax expense drawn from the cash hub (DR expense
        / CR cash); a negative amount -- a refundable credit -- reverses it. Returns the posted
        transaction, or None for a zero amount, so a caller can reference it in a Notice."""
        amount = quantize_money( amount )
        if amount == 0:
            return None
        chart = bookkeeper.chart
        cash_account = chart.cash_account()
        if cash_account is None:
            raise MissingAccountError( 'No cash account to pay tax from.' )
        expense_account = chart.expense_account( expense_class )
        if expense_account is None:
            raise MissingAccountError(
                f'No expense account for expense tax-class {expense_class.label}.' )
        return bookkeeper.record(
            settle_date, [ ( expense_account, -amount ), ( cash_account, amount ) ],
            description = description )

    def _assess_penalties( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """At the tax-year close, book the penalties the engine reads from the books view (the
        early-withdrawal penalty) -- each a tax expense from cash, with a WARNING Notice linked
        to its charge (the charge's memo carries the reason). Reading the whole year's
        distributions from the books (not this interval's events) means it sees them however
        they arose, funding draws included; the engine owns the rule."""
        fiscal_window = self._fiscal_window( bookkeeper )
        if fiscal_window is None:
            return
        penalties = self._parameters.tax_engine.assess_penalties(
            fiscal_window, self._parameters.tax_context )
        settle_date = self._parameters.date_span.end_date
        for penalty in penalties:
            charge = self._book_charge(
                bookkeeper, penalty.tax_class, penalty.amount, settle_date,
                description = penalty.reason )
            if charge is None:
                continue
            result.notices.append(
                Notice(
                    kind             = NoticeKind.EARLY_WITHDRAWAL_PENALTY,
                    severity         = NoticeSeverity.WARNING,
                    amount           = penalty.amount,
                    transaction_uuid = charge.transaction_uuid ) )
            continue
        return

    def _check_forced_tax_transactions( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """At the tax-year close, apply the transactions the tax law forces (RMDs today): the
        engine reads the books view and returns them; the Period executes each as a realization
        to cash, with an INFO Notice linked to it (the transaction's memo carries the reason).
        Run first among the close steps, so the forced income is funded and taxed with the
        rest."""
        fiscal_window = self._fiscal_window( bookkeeper )
        if fiscal_window is None:
            return
        forced = self._parameters.tax_engine.forced_transactions(
            fiscal_window, self._parameters.tax_context )
        if not forced:
            return
        period_end = self._parameters.date_span.end_date
        cash_account = bookkeeper.chart.cash_account()
        if cash_account is None:
            raise MissingAccountError( 'No cash account to receive forced distributions.' )
        for forced_transaction in forced:
            transaction = Realization(
                period_end, forced_transaction.account, forced_transaction.amount, cash_account
            ).apply( bookkeeper, description = forced_transaction.reason )
            if transaction is None:
                continue
            result.notices.append(
                Notice(
                    kind             = NoticeKind.REQUIRED_MINIMUM_DISTRIBUTION,
                    severity         = NoticeSeverity.INFO,
                    amount           = forced_transaction.amount,
                    transaction_uuid = transaction.transaction_uuid ) )
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
            transaction = bookkeeper.realize(
                source,
                draw,
                proceeds_account = cash_account,
                realized_gain_account = realized_gain_account,
                on_date = fund_date,
                description = f'Funding draw from {source} to cover a savings shortfall.',
            )
            if transaction is not None:
                result.notices.append(
                    Notice(
                        kind             = NoticeKind.FUNDING_DRAW,
                        severity         = NoticeSeverity.INFO,
                        amount           = draw,
                        transaction_uuid = transaction.transaction_uuid ) )
            continue
        return

    def _close( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Finalize the period: warn on a cash shortfall (the balance went negative) and flag
        the stop condition when net worth is depleted (assets no longer cover liabilities),
        which ends the Forecast. Both are constraint outcomes the user did not request, so both
        raise a WARNING Notice (state-level, with no linked transaction)."""
        ledger = bookkeeper.ledger
        cash_account = bookkeeper.chart.cash_account()
        if cash_account is not None:
            cash_balance = ledger.natural_balance( cash_account )
            if cash_balance < 0:
                result.notices.append(
                    Notice(
                        kind     = NoticeKind.CASH_SHORTFALL,
                        severity = NoticeSeverity.WARNING,
                        amount   = cash_balance ) )
        net_worth = ledger.net_worth()
        if net_worth <= 0:
            result.is_depleted = True
            result.notices.append(
                Notice(
                    kind     = NoticeKind.NET_WORTH_DEPLETED,
                    severity = NoticeSeverity.WARNING,
                    amount   = net_worth ) )
        return
