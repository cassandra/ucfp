"""The Period: one step of a Forecast.

A Period is a pure, myopic computation. It takes the Forecast's running books (a
`Bookkeeper`) and this interval's already-resolved `PeriodParameters`, posts the
interval's transactions onto those books, and returns the `Notice`s it raised and the
period's outcome. It does no time math (the Scenario resolves parameters across time) and
treats tax as a pluggable black box (the `TaxEngine` carried on its `PeriodParameters`,
resolved by the Scenario from the tax-law projection).

The interval is computed in three phases (see `ucfp/FORECAST_ENGINE.md`):
  1. Accrue        -- effects whose magnitude is known up front: asset growth and
                      distributions, income, liability service, scheduled expenses
                      and money-movement events, each at its temporal-POV instant.
  2. Settle & fund -- pay last year's tax (the Taxes Payable carried in), fund cash to
                      the floor via the funding waterfall (so the back-dated draw covers
                      that payment and the draws' realized income is taxed this year),
                      then accrue this year's tax to Taxes Payable -- owed now, paid next
                      year. The payment precedes funding, so cash stays at the floor.
  3. Close         -- finalize ending balances and the stop condition.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from ucfp.accounts.books import Transaction
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import ExpenseTaxClass, SystemAccountRole
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.accounts.money_utils import format_money, quantize_money
from ucfp.jurisdiction.engine import ContributionKind

from .events import Realization
from .parameters import PeriodParameters
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
        self._withhold_employment_tax( bookkeeper, result )
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
            # A depreciating holding accrues a negative appreciation; name the motion and show its rate
            # as a positive magnitude, so the memo reads 'depreciation: 18% on ...', not '-18%'.
            motion, shown_rate = (
                ( 'appreciation', rate ) if appreciation > 0 else ( 'depreciation', rate.negated() ) )
            bookkeeper.record(
                growth_date,
                [ ( valuation_account, -appreciation ), ( unrealized_gain_account, appreciation ) ],
                description = f'{holding.name} {motion}: {shown_rate} on {format_money( opening_market )}',
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
            # A non-positive opening balance is not a yield-bearing position: a depleted or
            # overdrawn cash hub is a shortfall, not principal. Applying the distribution rate
            # to it would book negative "income" and deepen the very hole it reacts to, so no
            # distribution is recognized until the balance is positive again.
            if opening_value <= 0:
                continue
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
                description = f'{holding.name} distribution: {rate} on {format_money( opening_value )}',
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
                description = income_line.source or '',
            )
            continue
        return

    def _withhold_employment_tax( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Withhold this interval's employment tax (US FICA: Social Security + Medicare) to cash, at
        the midpoint alongside the wages it rides on -- paid in-year as earned, not deferred to the tax
        payable like income tax. FICA carries annual, per-worker figures (the Social Security cap, the
        Medicare surtax threshold), so the engine reads it over the year-to-date window and this pays
        only the portion not yet withheld this tax year: the whole year in one step at annual
        granularity, each interval's increment at finer ones. No engine, or nothing left to withhold,
        means nothing to do."""
        tax_engine = self._parameters.tax_engine
        if tax_engine is None:
            return
        fiscal_window = self._parameters.fiscal_window
        year_to_date = tax_engine.assess_employment_tax( fiscal_window, self._parameters.tax_context )
        chart = bookkeeper.chart
        employment_tax_account = chart.expense_account( ExpenseTaxClass.EMPLOYMENT_TAX )
        if employment_tax_account is None:
            raise MissingAccountError( 'No employment-tax expense account to withhold to.' )
        already_withheld = bookkeeper.ledger.natural_flow(
            employment_tax_account,
            start = fiscal_window.span.start_date, end = fiscal_window.span.end_date )
        withholding = quantize_money( year_to_date - already_withheld )
        if withholding == 0:
            return
        cash_account = chart.cash_account()
        if cash_account is None:
            raise MissingAccountError( 'No cash account to withhold employment tax from.' )
        bookkeeper.record(
            self._parameters.date_span.midpoint,
            [ ( employment_tax_account, -withholding ), ( cash_account, withholding ) ],
            description = 'FICA withholding' )
        return

    def _apply_contributions( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Post the resolved retirement `contribution_lines` at the midpoint (after income, so
        cash is present): DR the target holding's valuation companion / CR its funding account --
        cash for an employee contribution (net-worth-neutral), External Receipts equity for an
        employer match (net-worth-increasing). Each line is first scaled by its (owner, kind)
        annual-limit factor (see `_contribution_cap_factors`): a contribution that has outgrown
        what the year's limit still allows is clamped and raises a Notice. An uncapped line is a
        requested input, so it carries a memo, not a Notice."""
        chart = bookkeeper.chart
        contribution_date = self._parameters.date_span.midpoint
        cap_factors = self._contribution_cap_factors( bookkeeper, result )
        for line in self._parameters.contribution_lines:
            factor = cap_factors.get( ( str( line.holding.owner_handle ), line.kind ), Decimal( '1' ) )
            amount = quantize_money( line.amount * factor )
            if amount == 0:
                continue
            valuation_account = chart.valuation_of( line.holding )
            if valuation_account is None:
                raise MissingAccountError(
                    f'Retirement holding "{line.holding}" has no valuation account to contribute to.' )
            bookkeeper.record(
                contribution_date,
                [ ( valuation_account, -amount ), ( line.funding_account, amount ) ],
                description = line.description,
            )
            continue
        return

    def _contribution_cap_factors(
            self, bookkeeper : Bookkeeper,
            result : PeriodResult ) -> dict[ tuple[ str, Optional[ ContributionKind ] ], Decimal ]:
        """The scale factor (< 1) for each (owner, kind) group whose contributions this interval
        overrun the annual headroom -- the limit less what the books already show contributed this
        tax year (read from the year-to-date fiscal window, the same pattern the RMD uses). The
        headroom is shared, so a group's contributions are summed and scaled together to fit it,
        and the group raises one WARNING Notice. Groups within headroom and the no-limit employer
        match are absent, leaving their lines unscaled. Correct at any granularity: the books carry
        prior sub-periods' contributions, so the running total is always whole-year."""
        tax_engine = self._parameters.tax_engine
        if tax_engine is None:
            return dict()
        tax_context = self._parameters.tax_context
        year_to_date = self._parameters.fiscal_window
        groups = dict()           # ( owner string, kind ) -> { intended amount, target holdings }
        for line in self._parameters.contribution_lines:
            if line.kind is None:
                continue
            key = ( str( line.holding.owner_handle ), line.kind )
            group = groups.setdefault( key, { 'intended' : Decimal( '0' ), 'holdings' : list() } )
            group[ 'intended' ] += quantize_money( line.amount )
            group[ 'holdings' ].append( line.holding )
            continue
        factors = dict()
        for ( owner, kind ), group in groups.items():
            subject = tax_context.subject_for( owner )
            if subject is None:
                continue
            limit = tax_engine.contribution_limit( kind, subject.age )
            if limit is None:
                continue
            contributed = sum(
                ( year_to_date.contributions_from_cash( holding ) for holding in group[ 'holdings' ] ),
                Decimal( '0' ) )
            headroom = max( Decimal( '0' ), limit - contributed )
            if group[ 'intended' ] <= headroom:
                continue
            factors[ ( owner, kind ) ] = headroom / group[ 'intended' ]
            result.notices.append(
                Notice(
                    kind     = NoticeKind.CONTRIBUTION_CAPPED,
                    severity = NoticeSeverity.WARNING,
                    amount   = quantize_money( group[ 'intended' ] - headroom ) ) )
            continue
        return factors

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
                description = (
                    f'{term.liability_account.name} payment: {format_money( interest )} interest '
                    f'+ {format_money( total_principal )} principal' ),
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
        """Apply each scheduled PeriodEvent (transfer, purchase, realization, external
        receipt/disbursement); each materializes its own balanced transaction. Scheduled events are the
        user's requested operations, so they raise no Notices -- except a property sale, whose *closing
        costs* are an automatic consequence worth surfacing, overlaid here after the sale realizes."""
        for event in self._parameters.events:
            sale_price = self._property_sale_price( bookkeeper, event )
            event.apply( bookkeeper )
            if sale_price is not None:
                self._book_property_sale_costs( bookkeeper, result, event, sale_price )
            continue
        return

    @staticmethod
    def _property_sale_price( bookkeeper : Bookkeeper, event ) -> Optional[ Decimal ]:
        """The market value of a real-estate holding about to be sold whole -- the sale price its
        closing costs scale against -- captured *before* the realize draws it down. None for any other
        event (a withdrawal, a conversion, a non-real-estate sale) or a valueless holding (no real sale
        to charge against, mirroring `realize`'s own zero-value guard)."""
        if not ( isinstance( event, Realization ) and event.amount is None
                 and event.holding.asset_class.is_real_estate ):
            return None
        market = bookkeeper.ledger.market_value( event.holding )
        return market if market > 0 else None

    def _book_property_sale_costs(
            self, bookkeeper : Bookkeeper, result : PeriodResult, event, sale_price : Decimal ) -> None:
        """Overlay a property sale's closing costs: the realtor fee (a share of the sale price) plus the
        already-inflated fixed costs. Booked as a cost of sale -- DR the realized-gain account / CR cash
        -- so it reduces both the net proceeds and the taxable gain (no separate account), with an INFO
        Notice whose linked transaction memo carries the breakdown."""
        realtor_fee = quantize_money(
            self._parameters.property_sale_realtor_fee_rate.change_on( sale_price ) )
        fixed = quantize_money( self._parameters.property_sale_fixed_cost )
        total = realtor_fee + fixed
        if total <= 0:
            return
        chart = bookkeeper.chart
        cash_account = chart.cash_account()
        # Real-estate gains are household income (never owner-attributed), so the cost of sale resolves
        # the gain account with no owner_handle -- unlike the owner-scoped retirement-distribution path.
        gain_account = chart.income_account( event.holding.asset_class.realized_gain_income_class )
        if cash_account is None or gain_account is None:
            return
        net = quantize_money( sale_price ) - total
        description = (
            f'Selling costs on {event.holding.name}: {format_money( realtor_fee )} realtor fee + '
            f'{format_money( fixed )} fixed costs on a {format_money( sale_price )} sale '
            f'(net {format_money( net )}).' )
        transaction = bookkeeper.record(
            event.event_date, [ ( gain_account, -total ), ( cash_account, total ) ],
            description = description )
        result.notices.append(
            Notice(
                kind             = NoticeKind.PROPERTY_SALE_COSTS,
                severity         = NoticeSeverity.INFO,
                amount           = total,
                transaction_uuid = transaction.transaction_uuid ) )
        return

    def _settle_and_fund( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Pay last year's tax first (the Taxes Payable carried in), then fund cash up to the
        policy's floor -- so the funding draw covers that payment along with the year's expenses,
        and the draws' realized income is taxed this year (accrued below, paid next year). Then
        accrue this year's tax to Taxes Payable, and finally sweep any surplus above the ceiling
        into investments (a basis-establishing purchase, so it is not a taxable event and rightly
        runs after settlement). Because the tax payment precedes funding, the back-dated draw keeps
        cash at the floor rather than letting tax punch it negative; only a net worth at or below
        zero ends the forecast (see _close). And because all funding precedes accrual, no untaxed
        income is ever carried -- only the payable is, deliberately, to next year's payment."""
        self._pay_prior_tax_payable( bookkeeper, result )
        self._check_forced_tax_transactions( bookkeeper, result )
        self._fund_to_target( bookkeeper, result )
        self._assess_penalties( bookkeeper, result )
        self._settle_tax( bookkeeper, result )
        self._sweep_to_ceiling( bookkeeper, result )
        return

    def _pay_prior_tax_payable( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Settle the Taxes Payable carried in from last year's accrual, on the payment date the tax
        law sets (civil default: April 15). One sign-agnostic entry (DR Taxes Payable / CR cash)
        settles either direction: a positive balance is paid out, a negative one -- a refund
        receivable from credits beyond the tax -- is collected in. Runs before the funding draw so
        the draw, back-dated to the year's start, has already covered the outflow by the time it
        lands in the journal, and before this year's accrual so it settles only the prior balance.
        No engine, no Taxes Payable account, a zero balance, or a payment date outside this interval
        -> nothing to do."""
        tax_engine = self._parameters.tax_engine
        if tax_engine is None:
            return
        chart = bookkeeper.chart
        taxes_payable = chart.system_account( SystemAccountRole.TAXES_PAYABLE )
        if taxes_payable is None:
            return
        span = self._parameters.date_span
        payment_date = tax_engine.tax_payment_date( span.start_date.year - 1 )
        if not ( span.start_date <= payment_date <= span.end_date ):
            return
        owed = bookkeeper.ledger.natural_balance( taxes_payable )
        if owed == 0:
            return
        cash_account = chart.cash_account()
        if cash_account is None:
            raise MissingAccountError( 'No cash account to settle Taxes Payable from.' )
        bookkeeper.record(
            payment_date, [ ( taxes_payable, -owed ), ( cash_account, owed ) ],
            description = 'Prior-year tax settlement' )
        return

    def _is_close_of_tax_year( self ) -> bool:
        """Whether this interval ends a tax year -- the explicit gate for the annual-only tax
        steps (settle, penalties, forced transactions). The engine, carried every interval, owns
        the boundary; no engine means no tax, so never. The fiscal window exists every interval
        regardless: this predicate, not the window's absence, is what gates the annual work."""
        tax_engine = self._parameters.tax_engine
        return ( tax_engine is not None ) and tax_engine.closes_tax_year(
            self._parameters.date_span.end_date )

    def _settle_tax( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Assess the tax year and accrue each charge to Taxes Payable, dated the year's end --
        owed now, paid the following year (see `_pay_prior_tax_payable`). (The zero-tax engine
        yields none.) Settlement runs only at the tax-year close.

        The engine's opening tax state (carryforwards) is threaded in, and its closing
        state captured on the result -- even in a no-charge year, since a capital-loss year
        produces a carryover with no tax due.

        Charges accrue as owed (DR tax expense / CR Taxes Payable); refundable credits are the
        reverse (CR the tax expense / DR Taxes Payable), so a credit beyond the matching tax leaves
        a net refund -- modeled here as a negated charge against the same expense class.

        Income tax is assessed only on a whole calendar year: a partial year (a mid-year start
        or a trailing year short of December 31) is not a `full_tax_year`, so this returns before
        assessing even at its year-close -- leaving it posted but untaxed. (The engine's other,
        exact rules still run; only this bracket-driven settlement is gated.)"""
        if not ( self._is_close_of_tax_year() and self._parameters.full_tax_year ):
            return
        fiscal_window = self._parameters.fiscal_window
        assessment = self._parameters.tax_engine.assess(
            fiscal_window, self._parameters.tax_context, self._parameters.opening_tax_state )
        result.closing_tax_state = assessment.closing_tax_state
        settlements = (
            [ ( charge.tax_class, charge.amount ) for charge in assessment.charges ]
            + [ ( credit.tax_class, -credit.amount ) for credit in assessment.credits ] )
        self._accrue_tax_charges( bookkeeper, settlements, self._parameters.date_span.end_date )
        return

    def _accrue_tax_charges( self, bookkeeper : Bookkeeper,
                             settlements : list[ tuple[ ExpenseTaxClass, Decimal ] ],
                             settle_date : date ) -> None:
        """Accrue each `(tax expense-class, amount)` to Taxes Payable."""
        for expense_class, amount in settlements:
            self._accrue_tax_charge( bookkeeper, expense_class, amount, settle_date )
            continue
        return

    def _accrue_tax_charge( self, bookkeeper : Bookkeeper, expense_class : ExpenseTaxClass,
                            amount : Decimal, settle_date : date,
                            description : str = '' ) -> Optional[ Transaction ]:
        """Accrue one `expense_class` tax charge as owed but not yet paid (DR tax expense
        / CR Taxes Payable); a negative amount -- a refundable credit -- reverses it, which can
        leave the payable negative (a refund receivable). The liability is settled to cash the
        following year (see `_pay_prior_tax_payable`). Returns the posted transaction, or None
        for a zero amount, so a caller can reference it in a Notice."""
        amount = quantize_money( amount )
        if amount == 0:
            return None
        chart = bookkeeper.chart
        taxes_payable = chart.system_account( SystemAccountRole.TAXES_PAYABLE )
        if taxes_payable is None:
            raise MissingAccountError( 'No Taxes Payable account to accrue tax to.' )
        expense_account = chart.expense_account( expense_class )
        if expense_account is None:
            raise MissingAccountError(
                f'No expense account for expense tax-class {expense_class.label}.' )
        return bookkeeper.record(
            settle_date, [ ( expense_account, -amount ), ( taxes_payable, amount ) ],
            description = description )

    def _assess_penalties( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """At the tax-year close, accrue the penalties the engine reads from the books view (the
        early-withdrawal penalty) -- each its own tax charge on Taxes Payable, with a WARNING Notice
        linked to its charge (the charge's memo carries the reason). Reading the whole year's
        distributions from the books (not this interval's events) means it sees them however
        they arose, funding draws included; the engine owns the rule."""
        if not self._is_close_of_tax_year():
            return
        fiscal_window = self._parameters.fiscal_window
        penalties = self._parameters.tax_engine.assess_penalties(
            fiscal_window, self._parameters.tax_context )
        settle_date = self._parameters.date_span.end_date
        for penalty in penalties:
            charge = self._accrue_tax_charge(
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
        if not self._is_close_of_tax_year():
            return
        fiscal_window = self._parameters.fiscal_window
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
        gains as it goes) until cash reaches the policy's cash_floor, or the
        sources are exhausted. Dated at the period start so the draw precedes the
        expenses it funds. A single pre-settlement pass: every gain it realizes is
        taxed this period, so nothing is carried but the ending cash balance."""
        chart = bookkeeper.chart
        ledger = bookkeeper.ledger
        cash_account = chart.cash_account()
        if cash_account is None:
            return
        target = self._parameters.funding_policy.cash_floor
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
                # A pre-tax draw's distribution posts to the owner's own revenue account; a taxable
                # gain to the single shared household one.
                owner_handle = source.owner_handle if income_class.is_owner_attributed else None
                realized_gain_account = chart.income_account( income_class, owner_handle )
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

    def _sweep_to_ceiling( self, bookkeeper : Bookkeeper, result : PeriodResult ) -> None:
        """Sweep any cash above the policy's ceiling into the sweep allocation as investments:
        each holding is debited its weighted share (DR holding (cost) / CR cash), so the swept
        amount becomes its cost basis and a later sale taxes only the gain. One balanced
        transaction. Shares are apportioned by cumulative rounding -- each portion is the rise in
        the running quantized target -- so every portion is non-negative (never a stray sell) and
        they sum exactly to the surplus (the weights sum to 1). Runs after settlement; it moves
        no income and is net-worth-neutral, so it raises no Notice (routine policy, requested --
        a memo suffices). No ceiling or no allocation means no sweep."""
        policy = self._parameters.funding_policy
        if ( policy.cash_ceiling is None ) or ( not policy.sweep_allocation ):
            return
        cash_account = bookkeeper.chart.cash_account()
        if cash_account is None:
            return
        surplus = quantize_money(
            bookkeeper.ledger.natural_balance( cash_account ) - policy.cash_ceiling )
        if surplus <= 0:
            return
        postings = list()
        cumulative_weight = Decimal( '0' )
        allocated = Decimal( '0' )
        for holding, weight in policy.sweep_allocation:
            cumulative_weight += weight
            target = quantize_money( surplus * cumulative_weight )
            postings.append( ( holding, -( target - allocated ) ) )
            allocated = target
            continue
        postings.append( ( cash_account, surplus ) )
        bookkeeper.record(
            self._parameters.date_span.end_date, postings,
            description = f'Swept {format_money( surplus )} of surplus cash into the investment allocation' )
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
