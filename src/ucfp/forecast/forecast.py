"""The Forecast: the N-step engine above the Period -- `ForecastParameters -> Forecast -> ForecastResult`.

The Forecast materializes a
`BooksOfAccount` from the asset/liability parameters (the "baseline" is encoded there, not
handed in), then walks the frame: resolve each interval's `PeriodParameters`, run the
`Period` on the running `Bookkeeper`, apply feedback knobs, thread `TaxState`, accumulate,
and stop at the horizon or net-worth depletion.

The whole run is in memory -- the `Bookkeeper`/`BooksOfAccount` domain touches no database
-- so the produced books are returned on the result; persisting them is the caller's job
(via the Repository), not the Forecast's.

Boundary (the running-state test): the Forecast owns only what needs the running
projection state -- per-period resolution that depends on the books, the feedback knobs,
state threading. Projection-independent expansion (profiles, ladders, segment timelines)
is upstream materialization that builds the `ForecastParameters`.

It selects the tax law via the parameters' `TaxForecastProfile` and treats the resulting
engine as a black box: it asks the `TaxLaw` for each year's engine and never touches a
tax knob.
"""
import calendar
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from common.date_window import DateWindow
from ucfp.accounts.books import Account, BooksOfAccount
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import (
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
    SystemAccountRole,
)
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.period.parameters import (
    ContributionLine,
    DateSpan,
    ExpenseLine,
    FundingPolicy,
    IncomeLine,
    LiabilityTerm,
    PeriodParameters,
)
from ucfp.period.events import PeriodEvent
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult
from ucfp.tax.engine import ContributionKind
from ucfp.tax.law import TaxLaw
from ucfp.tax.subsidized_health import SubsidizedHealthEnrollment
from ucfp.tax.context import TaxContext, TaxSubject
from ucfp.tax.property import PropertyDisposition, TaxProperty

from .parameters import (
    ContributionSource,
    ExpenseItem,
    ExpenseStream,
    ForecastParameters,
    ScheduledRealization,
    Subject,
    resolve_household_size,
)


# Which annual contribution limit each source counts against (None = no employee limit). The
# WAGE/EMPLOYER split feeds the limit buckets: payroll deferrals are the employer-plan limit,
# direct contributions the personal (IRA) limit, an employer match neither.
_LIMIT_KIND_BY_SOURCE = {
    ContributionSource.WAGE     : ContributionKind.EMPLOYER_PLAN,
    ContributionSource.PERSONAL : ContributionKind.PERSONAL,
    ContributionSource.EMPLOYER : None,
}


# A loan resolved against the books: its parameters plus the accounts and the level
# payment (derived once by amortization) the per-interval term is computed from.
_ResolvedLoan = namedtuple( '_ResolvedLoan', ( 'parameters', 'account', 'interest_account', 'payment' ) )


def _amortized_payment( principal : Decimal, periodic_rate : Decimal, periods : int ) -> Decimal:
    """The level payment that retires `principal` over `periods` at `periodic_rate` per
    period -- the standard amortization formula (straight-line when the rate is zero)."""
    if periodic_rate == 0:
        return principal / periods
    discount = ( Decimal( '1' ) + periodic_rate ) ** ( -periods )
    return principal * periodic_rate / ( Decimal( '1' ) - discount )


@dataclass
class ForecastStep:
    """One interval's outcome within a run: its span and the Period's result. Per-step
    figures (net worth, cash) are *derived* from the result's books, not cached here."""

    span   : DateSpan
    result : PeriodResult


@dataclass
class ForecastResult:
    """What a Forecast run produces: the final `BooksOfAccount` (the complete record --
    every reported figure is derived from it), each interval's step, and whether it
    stopped early (net-worth depletion before the horizon)."""

    books         : BooksOfAccount
    steps         : list[ ForecastStep ] = field( default_factory = list )
    stopped_early : bool = False


class IncomeAccounts:
    """The revenue account for each `(subject, income tax-class)`, created on first request
    and reused after. It owns the account key, so creation and per-period posting resolve
    to the same account -- the key is defined here and nowhere else. Per subject so wages
    stay per-worker (the FICA cap) and Social Security per person. Each account carries its
    subject's handle as `owner_handle`, so the planner associates it by `(owner, class)` --
    many streams of one (subject, class) share the account, so it bears no own handle."""

    def __init__( self, bookkeeper : Bookkeeper ):
        self._bookkeeper = bookkeeper
        self._revenue_root = bookkeeper.chart.root( AccountType.REVENUE )
        self._account_by_key = dict()

    def account_for( self, subject : Subject, income_tax_class : IncomeTaxClass ) -> Account:
        """The revenue account for `subject`'s `income_tax_class` income, creating it under
        the Revenue root on first request."""
        key = ( subject, income_tax_class )
        account = self._account_by_key.get( key )
        if account is None:
            account = self._bookkeeper.add_account(
                Account(
                    name             = f'{subject.name} {income_tax_class.label}',
                    parent           = self._revenue_root,
                    income_tax_class = income_tax_class,
                    owner_handle     = subject.handle,
                )
            )
            self._account_by_key[ key ] = account
        return account


class ExpenseAccounts:
    """The expense account for each expense item or stream (keyed by name), created on first
    request and reused after -- the one place the expense-account key lives. Per item so the Books
    keep item-level detail; each account is tagged with the item's tax-class for the engine
    to aggregate by class."""

    def __init__( self, bookkeeper : Bookkeeper ):
        self._bookkeeper = bookkeeper
        self._expense_root = bookkeeper.chart.root( AccountType.EXPENSE )
        self._account_by_name = dict()

    def account_for( self, item : ExpenseItem | ExpenseStream ) -> Account:
        """The expense account for `item` (an occurrence-based item or a smooth stream), creating
        it under the Expenses root on first request and stamping its handle so the planner can
        associate it in results."""
        account = self._account_by_name.get( item.name )
        if account is None:
            account = self._bookkeeper.add_account(
                Account(
                    name              = item.name,
                    parent            = self._expense_root,
                    expense_tax_class = item.expense_tax_class,
                    handle            = item.handle,
                )
            )
            self._account_by_name[ item.name ] = account
        return account


@dataclass( frozen = True )
class ResolvedBaseline:
    """The immutable result of materializing a forecast's baseline: the seeded opening books and
    the resolved structures the run loop reads -- the holding lookups, the draw priority and sweep
    allocation, the loans, the periods-per-year, and the income/expense account registries. Built
    once by `BaselineBuilder`; the `Forecast` holds it and its per-interval resolvers read it."""

    bookkeeper        : Bookkeeper
    holding_by_handle : dict
    asset_holdings    : list
    draw_priority     : list
    sweep_allocation  : tuple
    loans             : list
    periods_per_year  : Optional[ int ]
    income_accounts   : IncomeAccounts
    expense_accounts  : ExpenseAccounts


class BaselineBuilder:
    """Materializes a `ForecastParameters` into the opening books and the resolved structures the
    run loop reads, validating the inputs as it goes. This is the one-time build phase, kept apart
    from the time-stepping `Forecast`: `build()` runs the create/resolve/validate steps once and
    returns an immutable `ResolvedBaseline`."""

    def __init__( self, parameters : ForecastParameters, tax_law : TaxLaw ):
        self._parameters = parameters
        self._tax_law    = tax_law
        self._income_accounts = None    # an IncomeAccounts, built with the books
        self._expense_accounts = None   # an ExpenseAccounts, built with the books
        self._holding_by_handle = dict()  # handle string -> holding account, for resolving events
        self._asset_holdings = list()   # (AssetParameters, holding) pairs, for property resolution
        self._draw_priority = list()    # holdings to fund from, resolved from draw_order by class
        self._sweep_allocation = ()     # resolved ( holding, weight ) pairs to sweep surplus into
        self._loans = list()            # resolved loans (accounts + level payment)
        self._periods_per_year = None   # set when there are liabilities (needs month/year granularity)

    def build( self ) -> ResolvedBaseline:
        """Build the chart and opening books from the parameters -- the baseline is encoded
        there, not handed in. One opening transaction seeds each holding's value (an asset)
        and each loan's balance (a liability) against Opening Balances, which absorbs the
        net (= opening net worth); revenue/expense accounts are created per income stream,
        per expense item, per loan's interest, and per tax-payment class."""
        bookkeeper = Bookkeeper( BooksOfAccount( label = self._parameters.label ) )
        bookkeeper.build_standard_chart()
        chart = bookkeeper.chart
        asset_root = chart.root( AccountType.ASSET )
        holdings = list()
        for asset in self._parameters.assets:
            holding = bookkeeper.create_holding(
                asset_root, asset.name, asset.asset_class,
                handle = asset.handle, owner_handle = asset.owner_handle )
            holdings.append( ( holding, asset.opening_value, asset.cost_basis ) )
            self._asset_holdings.append( ( asset, holding ) )
            if asset.handle is not None:
                self._holding_by_handle[ str( asset.handle ) ] = holding
            continue
        self._create_loans( bookkeeper )
        self._seed_opening_balances( bookkeeper, holdings )
        self._create_income_accounts( bookkeeper )
        self._create_asset_income_accounts( bookkeeper )
        self._create_expense_accounts( bookkeeper )
        self._create_tax_accounts( bookkeeper )
        self._resolve_draw_priority( bookkeeper )
        self._resolve_sweep( bookkeeper )
        self._validate_contributions( bookkeeper )
        return ResolvedBaseline(
            bookkeeper        = bookkeeper,
            holding_by_handle = self._holding_by_handle,
            asset_holdings    = self._asset_holdings,
            draw_priority     = self._draw_priority,
            sweep_allocation  = self._sweep_allocation,
            loans             = self._loans,
            periods_per_year  = self._periods_per_year,
            income_accounts   = self._income_accounts,
            expense_accounts  = self._expense_accounts,
        )

    def _validate_contributions( self, bookkeeper : Bookkeeper ) -> None:
        """Check each contribution's target is a retirement holding, and that an employer match
        lands in a pre-tax account (Roth employer match is deferred) -- rejected at build so a
        mis-targeted contribution cannot silently mismodel."""
        retirement = ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH )
        for contribution in self._parameters.contributions:
            holding = self._holding_by_handle.get( str( contribution.account ) )
            if ( holding is None ) or ( holding.asset_class not in retirement ):
                raise MissingAccountError(
                    f'Contribution targets "{contribution.account}", which is not a retirement '
                    'holding.' )
            if ( contribution.source == ContributionSource.EMPLOYER ) and (
                    holding.asset_class != AssetClass.PRETAX_RETIREMENT ):
                raise ValueError(
                    'An employer match must target a pre-tax retirement holding '
                    '(Roth employer match is not yet supported).' )
            continue
        self._reject_over_limit_contributions()
        return

    def _reject_over_limit_contributions( self ) -> None:
        """Reject inputs whose first-year contributions already exceed an annual limit -- a clear
        planner error, caught before the forecast runs. Contributions sharing an (owner, limit
        kind) share one limit, so they are aggregated. (Once iterating, a contribution that *grows*
        past its limit is clamped with a Notice instead, since the economy moved, not the planner.)"""
        start_date = self._parameters.start_date
        engine = self._tax_law.engine_for( start_date.year )
        intended = dict()                                  # ( owner string, kind ) -> first-year total
        for contribution in self._parameters.contributions:
            kind = _LIMIT_KIND_BY_SOURCE[ contribution.source ]
            if ( kind is None ) or ( not contribution.window.covers( start_date ) ):
                continue
            holding = self._holding_by_handle[ str( contribution.account ) ]
            key = ( str( holding.owner_handle ), kind )
            intended[ key ] = intended.get( key, Decimal( '0' ) ) + contribution.amount
            continue
        for ( owner, kind ), total in intended.items():
            age = self._owner_age( owner, start_date.year )
            if age is None:
                continue
            limit = engine.contribution_limit( kind, age )
            if ( limit is None ) or ( total <= limit ):
                continue
            raise ValueError(
                f'First-year retirement contributions for "{owner}" total {total}, over the '
                f'{limit} annual limit.' )
        return

    def _owner_age( self, owner : str, year : int ) -> Optional[ int ]:
        """The age at the end of `year` of the subject whose handle is `owner`, or None if no such
        subject is on the forecast (so no per-owner contribution limit can attach)."""
        for subject in self._parameters.subjects:
            if ( subject.handle is not None ) and ( str( subject.handle ) == owner ):
                return year - subject.birthdate.year
            continue
        return None

    def _seed_opening_balances( self, bookkeeper : Bookkeeper, holdings : list ) -> None:
        """Post the opening transaction: each holding's value (increasing the asset) and each
        loan's balance (a credit, the liability), with Opening Balances absorbing the residual
        so the books balance from t0. Each holding's embedded gain (value - basis) self-balances
        against its own Unrealized Gains equity, so only the bases and loans hit the plug."""
        chart = bookkeeper.chart
        opening_postings = list()
        for holding, value, cost_basis in holdings:
            opening_postings += self._opening_value_postings( chart, holding, value, cost_basis )
            continue
        opening_postings += [ ( loan.account, loan.parameters.opening_balance ) for loan in self._loans ]
        plug = -sum( ( amount for _account, amount in opening_postings ), Decimal( '0' ) )
        opening_postings.append(
            ( chart.system_account( SystemAccountRole.OPENING_BALANCES ), plug ) )
        if any( amount != 0 for _account, amount in opening_postings ):
            bookkeeper.record( self._parameters.start_date - timedelta( days = 1 ), opening_postings )
        return

    def _opening_value_postings( self, chart, holding : Account, value : Decimal,
                                 cost_basis : Decimal ) -> list[ tuple[ Account, Decimal ] ]:
        """The opening postings seeding `holding` to market `value` with tax basis
        `cost_basis`: the basis lands in the holding's cost account and any embedded gain
        (value - basis) in its valuation companion against its own Unrealized Gains equity, so
        a later realization recognizes the gain from the true basis, not from t0. A zero-basis
        retirement holding (basis 0) seeds its whole value as gain; a freshly-valued holding
        (basis = value) seeds cost = market with nothing unrealized."""
        embedded_gain = value - cost_basis
        postings = [ ( holding, -cost_basis ) ]
        if embedded_gain != 0:
            valuation_account = chart.valuation_of( holding )
            unrealized_gains = chart.system_account( SystemAccountRole.UNREALIZED_GAINS )
            postings += [ ( valuation_account, -embedded_gain ), ( unrealized_gains, embedded_gain ) ]
        return postings

    def _create_loans( self, bookkeeper : Bookkeeper ) -> None:
        """Create a liability account and an interest expense account per loan, and derive
        its level payment (amortizing the opening balance over the term at the run's
        granularity). Called before the opening seed, which credits each balance."""
        if not self._parameters.loans:
            return
        self._periods_per_year = 12 // self._parameters.granularity.months()
        liability_root = bookkeeper.chart.root( AccountType.LIABILITY )
        expense_root = bookkeeper.chart.root( AccountType.EXPENSE )
        for loan in self._parameters.loans:
            account = bookkeeper.add_account(
                Account( name = loan.name, parent = liability_root, handle = loan.handle ) )
            interest_account = bookkeeper.add_account(
                Account( name = f'{loan.name} Interest', parent = expense_root,
                         expense_tax_class = loan.interest_class, handle = loan.interest_handle ) )
            periodic_rate = loan.interest_rate.fraction / self._periods_per_year
            periods = loan.term.months() // self._parameters.granularity.months()
            payment = _amortized_payment( loan.opening_balance, periodic_rate, periods )
            self._loans.append( _ResolvedLoan( loan, account, interest_account, payment ) )
            continue
        return

    def _create_income_accounts( self, bookkeeper : Bookkeeper ) -> None:
        """Set up the income-account registry and pre-create an account for every stream and
        item, so the chart is complete from the start (each account exists even before its
        window opens). A stream and an item of the same (subject, class) share one account."""
        self._income_accounts = IncomeAccounts( bookkeeper )
        for stream in self._parameters.income_streams:
            self._income_accounts.account_for( stream.subject, stream.income_tax_class )
            continue
        for item in self._parameters.income_items:
            self._income_accounts.account_for( item.subject, item.income_tax_class )
            continue
        return

    def _create_expense_accounts( self, bookkeeper : Bookkeeper ) -> None:
        """Set up the expense-account registry and pre-create an account for every occurrence-based
        item and smooth stream, so the chart is complete from the start."""
        self._expense_accounts = ExpenseAccounts( bookkeeper )
        for item in self._parameters.expense_items:
            self._expense_accounts.account_for( item )
            continue
        for stream in self._parameters.expense_streams:
            self._expense_accounts.account_for( stream )
            continue
        return

    def _create_tax_accounts( self, bookkeeper : Bookkeeper ) -> None:
        """Create an expense account for each tax-payment class, so the year-close tax step
        has somewhere to post its charges and refundable credits."""
        expense_root = bookkeeper.chart.root( AccountType.EXPENSE )
        for expense_class in ExpenseTaxClass.all():
            if not expense_class.is_tax_payment:
                continue
            bookkeeper.add_account(
                Account( name = expense_class.label, parent = expense_root,
                         expense_tax_class = expense_class ) )
            continue
        return

    def _create_asset_income_accounts( self, bookkeeper : Bookkeeper ) -> None:
        """Create a revenue account for each income class the assets can generate -- yields
        (distributions) and realized gains -- that does not already have one, so a holding's
        distributions and a funding draw's recognized gain have somewhere to post."""
        chart = bookkeeper.chart
        revenue_root = chart.root( AccountType.REVENUE )
        income_classes = set()
        for asset in self._parameters.assets:
            income_classes.add( asset.asset_class.distribution_income_class )
            income_classes.add( asset.asset_class.realized_gain_income_class )
        income_classes.discard( None )
        for income_class in sorted( income_classes, key = lambda klass : klass.name ):
            if chart.income_account( income_class ) is None:
                bookkeeper.add_account(
                    Account( name = income_class.label, parent = revenue_root,
                             income_tax_class = income_class ) )
            continue
        return

    def _resolve_draw_priority( self, bookkeeper : Bookkeeper ) -> None:
        """Bind the cash policy's `draw_order` (asset classes, in priority) to the actual holding
        accounts: each class expands to its holdings (drawn sequentially), flattened into
        the order the funding waterfall draws from."""
        holdings = bookkeeper.chart.holdings()
        self._draw_priority = [
            holding for asset_class in self._parameters.cash_account.draw_order
            for holding in holdings if holding.asset_class == asset_class
        ]
        return

    def _resolve_sweep( self, bookkeeper : Bookkeeper ) -> None:
        """Resolve and validate the cash policy's sweep allocation: when a `cash_ceiling` is set
        it must be at or above `cash_floor` and have a `sweep_allocation` whose holdings are each
        non-retirement, non-cash (the surplus is invested at cost there). Binds each allocation
        handle to its holding. Rejected at build so a mis-configured sweep cannot mismodel."""
        cash = self._parameters.cash_account
        if cash.cash_ceiling is None:
            return
        if cash.cash_ceiling < cash.cash_floor:
            raise ValueError(
                f'cash_ceiling ({cash.cash_ceiling}) must be at or above cash_floor '
                f'({cash.cash_floor}).' )
        if cash.sweep_allocation is None:
            raise ValueError( 'A cash_ceiling requires a sweep_allocation to invest the surplus into.' )
        resolved = list()
        for handle, weight in cash.sweep_allocation.weights:
            holding = self._holding_by_handle.get( str( handle ) )
            if ( holding is None ) or ( holding.asset_class is None ):
                raise MissingAccountError( f'Sweep destination "{handle}" is not a holding.' )
            if holding.asset_class.seeds_at_zero_basis:
                raise ValueError(
                    f'Sweep destination "{handle}" is a retirement account; the sweep must invest '
                    'in taxable holdings (contribution limits are not modeled).' )
            if holding.asset_class == AssetClass.CASH:
                raise ValueError( f'Sweep destination "{handle}" is cash; it must be an investment.' )
            resolved.append( ( holding, weight ) )
            continue
        self._sweep_allocation = tuple( resolved )
        return


class Forecast:
    """Runs a `ForecastParameters` to completion (N Period steps); see the module
    docstring for the boundary."""

    def __init__( self, parameters : ForecastParameters ):
        self._parameters = parameters
        self._tax_law    = TaxLaw( parameters.tax_forecast )
        self._baseline   = None         # the ResolvedBaseline, materialized once at the start of run()

    def run( self ) -> ForecastResult:
        """Build the opening books from the parameters, then walk the frame running a
        Period per interval -- threading the tax state and stopping at depletion."""
        self._baseline = BaselineBuilder( self._parameters, self._tax_law ).build()
        bookkeeper    = self._baseline.bookkeeper
        result        = ForecastResult( books = bookkeeper.books )
        opening_state = self._parameters.initial_tax_state
        for span in self._parameters.period_spans():
            if self._parameters.subjects and not self._parameters.active_subjects( span.end_date.year ):
                result.stopped_early = True
                break
            self._retitle_removed_subjects_accounts( bookkeeper, span )
            period_parameters = self._build_period_parameters( span, opening_state, bookkeeper )
            period            = Period( period_parameters )
            period_result     = period.compute( bookkeeper )
            result.steps.append( ForecastStep( span, period_result ) )
            if period_result.closing_tax_state is not None:
                opening_state = period_result.closing_tax_state
            if period_result.is_depleted:
                result.stopped_early = True
                break
            continue
        return result

    def _liability_terms_for( self, bookkeeper : Bookkeeper ) -> list[ LiabilityTerm ]:
        """Resolve each outstanding loan's payment for the interval from its running balance:
        interest on the balance at the periodic rate, scheduled principal = level payment -
        interest, plus the prorated extra principal -- all capped at the remaining balance so
        the final payment pays it off. A loan with no balance left is skipped."""
        ledger = bookkeeper.ledger
        terms = list()
        for loan in self._baseline.loans:
            balance = ledger.natural_balance( loan.account )
            if balance <= 0:
                continue
            interest = balance * ( loan.parameters.interest_rate.fraction / self._baseline.periods_per_year )
            principal = min( max( loan.payment - interest, Decimal( '0' ) ), balance )
            per_period_extra = loan.parameters.annual_extra_principal / self._baseline.periods_per_year
            extra = min( per_period_extra, balance - principal )
            terms.append(
                LiabilityTerm(
                    liability_account = loan.account,
                    interest_account  = loan.interest_account,
                    principal         = principal,
                    interest          = interest,
                    extra_principal   = extra,
                )
            )
            continue
        return terms

    def _income_lines_for( self, span : DateSpan, year_fraction : Decimal ) -> list[ IncomeLine ]:
        """All income IncomeLines for this interval: the smooth streams (prorated) plus the
        occurrence-based items (placed by their cadence). The income counterpart of
        `_expense_lines_for`."""
        return ( self._income_stream_lines_for( span, year_fraction )
                 + self._income_item_lines_for( span ) )

    def _income_stream_lines_for( self, span : DateSpan, year_fraction : Decimal ) -> list[ IncomeLine ]:
        """Resolve the income streams active this interval into IncomeLines: take each stream's
        level then in effect, grow it to nominal by its class rate from the forecast start,
        prorate to the interval's share of the year, and post to its per-(subject, class) account."""
        lines = list()
        for stream in self._parameters.income_streams:
            if not stream.window.covers( span.start_date ):
                continue
            windowed_amount = stream.amounts.at( span.start_date )
            if windowed_amount is None:
                continue
            factor = self._income_growth_factor( stream.income_tax_class, span.start_date.year )
            amount = windowed_amount.amount * factor * year_fraction
            account = self._baseline.income_accounts.account_for( stream.subject, stream.income_tax_class )
            lines.append( IncomeLine( account = account, gross_amount = amount ) )
            continue
        return lines

    def _income_item_lines_for( self, span : DateSpan ) -> list[ IncomeLine ]:
        """Resolve the occurrence-based income items active this interval into IncomeLines: the
        cadence's occurrences in the interval x the per-occurrence amount in effect (grown to
        nominal from the forecast start), posted to the per-(subject, class) account. The income
        counterpart of `_expense_item_lines_for` -- a `OneTime` cadence makes it a single receipt."""
        lines = list()
        for item in self._parameters.income_items:
            clipped = self._clip_to_window( span, item.window )
            if clipped is None:
                continue
            start, end = clipped
            since = item.window.start if item.window.start is not None else self._parameters.start_date
            occurrences = item.cadence.count_in( start = start, end = end, since = since )
            windowed_amount = item.amounts.at( span.start_date )
            if ( occurrences == 0 ) or ( windowed_amount is None ):
                continue
            factor = self._income_growth_factor( item.income_tax_class, span.start_date.year )
            account = self._baseline.income_accounts.account_for( item.subject, item.income_tax_class )
            lines.append(
                IncomeLine( account = account, gross_amount = occurrences * windowed_amount.amount * factor ) )
            continue
        return lines

    def _contribution_lines_for(
            self, span : DateSpan, year_fraction : Decimal,
            bookkeeper : Bookkeeper ) -> list[ ContributionLine ]:
        """Resolve the retirement contributions active this interval into ContributionLines:
        grow each by wage growth from the forecast start and prorate to the interval. The line
        names the target holding (the Period posts into its valuation companion and clamps the
        contribution to its annual limit) and the funding source -- cash for an employee
        contribution, External Receipts equity for an employer match."""
        chart = bookkeeper.chart
        external_receipts = chart.system_account( SystemAccountRole.EXTERNAL_RECEIPTS )
        lines = list()
        for contribution in self._parameters.contributions:
            if not contribution.window.covers( span.start_date ):
                continue
            holding = self._baseline.holding_by_handle[ str( contribution.account ) ]
            funding_account = chart.cash_account()
            if contribution.source == ContributionSource.EMPLOYER:
                funding_account = external_receipts
            if funding_account is None:
                raise MissingAccountError( 'No account to fund the retirement contribution from.' )
            factor = self._income_growth_factor( IncomeTaxClass.WAGES, span.start_date.year )
            amount = contribution.amount * factor * year_fraction
            lines.append(
                ContributionLine(
                    holding         = holding,
                    funding_account = funding_account,
                    amount          = amount,
                    kind            = _LIMIT_KIND_BY_SOURCE[ contribution.source ],
                    description     = f'{contribution.source.label} contribution to {holding}' ) )
            continue
        return lines

    def _expense_lines_for( self, span : DateSpan, year_fraction : Decimal ) -> list[ ExpenseLine ]:
        """All expense ExpenseLines for this interval: the occurrence-based items (placed by their
        recurrence) plus the smooth streams (prorated like income)."""
        return ( self._expense_item_lines_for( span )
                 + self._expense_stream_lines_for( span, year_fraction ) )

    def _expense_item_lines_for( self, span : DateSpan ) -> list[ ExpenseLine ]:
        """Resolve the occurrence-based expense items active this interval into ExpenseLines: the
        cadence's occurrences in the interval x the per-occurrence amount in effect (inflated
        from the forecast start), posted to the item's account."""
        lines = list()
        for item in self._parameters.expense_items:
            clipped = self._clip_to_window( span, item.window )
            if clipped is None:
                continue
            start, end = clipped
            since = item.window.start if item.window.start is not None else self._parameters.start_date
            occurrences = item.cadence.count_in( start = start, end = end, since = since )
            windowed_amount = item.amounts.at( span.start_date )
            if ( occurrences == 0 ) or ( windowed_amount is None ):
                continue
            factor = self._expense_inflation_factor( item.expense_tax_class, span.start_date.year )
            account = self._baseline.expense_accounts.account_for( item )
            lines.append(
                ExpenseLine( account = account, amount = occurrences * windowed_amount.amount * factor ) )
            continue
        return lines

    def _expense_stream_lines_for( self, span : DateSpan, year_fraction : Decimal ) -> list[ ExpenseLine ]:
        """Resolve the smooth expense streams active this interval into ExpenseLines: take each
        stream's level then in effect, inflate it to nominal by its class rate from the forecast
        start, and prorate to the interval's share of the year, posting to its account. The
        expense counterpart of `_income_lines_for`."""
        lines = list()
        for stream in self._parameters.expense_streams:
            if not stream.window.covers( span.start_date ):
                continue
            windowed_amount = stream.amounts.at( span.start_date )
            if windowed_amount is None:
                continue
            factor = self._expense_inflation_factor( stream.expense_tax_class, span.start_date.year )
            amount = windowed_amount.amount * factor * year_fraction
            account = self._baseline.expense_accounts.account_for( stream )
            lines.append( ExpenseLine( account = account, amount = amount ) )
            continue
        return lines

    def _events_for( self, span : DateSpan, bookkeeper : Bookkeeper ) -> list[ PeriodEvent ]:
        """Resolve the scheduled events occurring in this interval into PeriodEvents, binding
        their holding handles to the running accounts (and via the chart the cash hub and the
        equity accounts an external receipt/disbursement moves). Order is preserved, so
        same-interval events apply as authored."""
        chart = bookkeeper.chart
        return [
            event.to_period_event( self._baseline.holding_by_handle, chart )
            for event in self._parameters.events if event.in_span( span ) ]

    def _clip_to_window( self, span : DateSpan, window : DateWindow ) -> Optional[ tuple[ date, date ] ]:
        """The inclusive `[start, end]` overlap of `span` and `window`, or None if they do
        not overlap."""
        start = span.start_date
        end = span.end_date
        if ( window.start is not None ) and ( window.start > start ):
            start = window.start
        if ( window.end is not None ) and ( window.end < end ):
            end = window.end
        if start > end:
            return None
        return ( start, end )

    def _income_growth_factor( self, income_tax_class : IncomeTaxClass, target_year : int ) -> Decimal:
        return self._cumulative_factor(
            target_year, lambda segment : segment.income_growth_rate( income_tax_class ) )

    def _expense_inflation_factor( self, expense_tax_class : ExpenseTaxClass, target_year : int ) -> Decimal:
        return self._cumulative_factor(
            target_year, lambda segment : segment.expense_inflation_rate( expense_tax_class ) )

    def _inflation_factor( self, target_year : int ) -> Decimal:
        """Cumulative general inflation from the forecast start to `target_year` -- used to keep
        the cash band (a cost-of-living buffer) constant in real terms."""
        return self._cumulative_factor( target_year, lambda segment : segment.inflation )

    def _funding_policy_for( self, span : DateSpan ) -> FundingPolicy:
        """The cash-management policy for the interval: the floor and ceiling are today's-dollars
        buffers grown to this year's level by general inflation (a level, so not prorated), while
        the resolved draw priority and sweep destination are fixed for the run."""
        cash = self._parameters.cash_account
        inflation = self._inflation_factor( span.start_date.year )
        ceiling = None if cash.cash_ceiling is None else ( cash.cash_ceiling * inflation )
        return FundingPolicy(
            cash_floor       = cash.cash_floor * inflation,
            draw_priority    = self._baseline.draw_priority,
            cash_ceiling     = ceiling,
            sweep_allocation = self._baseline.sweep_allocation )

    def _cumulative_factor( self, target_year : int, rate_for ) -> Decimal:
        """Cumulative growth from the forecast start year to `target_year`, compounding each
        year's economic-outlook rate (selected by `rate_for`, a segment -> Rate) -- so a
        today's-dollar amount becomes that year's nominal. 1.0 in the start year. (Annual
        indexing: every sub-period of a year shares that year's level, at any granularity.)"""
        factor = Decimal( '1' )
        for year in range( self._parameters.start_date.year + 1, target_year + 1 ):
            segment = self._parameters.economic_outlook.parameters_at( date( year, 1, 1 ) )
            factor *= ( Decimal( '1' ) + rate_for( segment ).fraction )
            continue
        return factor

    def _build_period_parameters( self, span : DateSpan, opening_tax_state,
                                  bookkeeper : Bookkeeper ) -> PeriodParameters:
        """Build this interval's myopic PeriodParameters. Rates and flows are resolved to
        the interval's length (so the same parameters run at any granularity), and liability
        terms are amortized off the running balance. The year's tax engine is carried every
        interval; the Period asks it whether the interval closes a tax year and settles only
        then."""
        year_fraction = self._year_fraction( span )
        annual_rates = self._parameters.economic_outlook.asset_rates_at( span.start_date )
        return PeriodParameters(
            date_span         = span,
            tax_context       = self._tax_context_for( span ),
            asset_rates       = annual_rates.over_fraction( year_fraction ),
            income_lines      = self._income_lines_for( span, year_fraction ),
            expense_lines     = self._expense_lines_for( span, year_fraction ),
            liability_terms   = self._liability_terms_for( bookkeeper ),
            contribution_lines = self._contribution_lines_for( span, year_fraction, bookkeeper ),
            events            = self._events_for( span, bookkeeper ),
            funding_policy    = self._funding_policy_for( span ),
            tax_engine        = self._tax_law.engine_for( span.end_date.year ),
            opening_tax_state = opening_tax_state,
        )

    def _year_fraction( self, span : DateSpan ) -> Decimal:
        """The interval's share of its calendar year (`days / days-in-year`), used to scale
        annual rates and income to the interval. 1 for a full calendar year; the months of
        a year sum back to 1."""
        period_days = ( span.end_date - span.start_date ).days + 1
        year_days = 366 if calendar.isleap( span.start_date.year ) else 365
        return Decimal( period_days ) / Decimal( year_days )

    def _retitle_removed_subjects_accounts( self, bookkeeper : Bookkeeper, span : DateSpan ) -> None:
        """Retitle a decedent's accounts to the survivor once the run passes the death year, so
        the survivor's age then drives the account's RMDs and early-withdrawal penalty. The
        scan is idempotent -- after a retitle the accounts no longer carry the decedent's
        handle -- so it can run each period. No survivor (the last death) leaves them as-is;
        the plan ends instead."""
        year = span.end_date.year
        for removal in self._parameters.subject_removals:
            if year <= removal.event_date.year:
                continue
            survivor_handle = self._parameters.survivor_handle( removal.subject_handle )
            if survivor_handle is None:
                continue
            bookkeeper.retitle_owner( removal.subject_handle, survivor_handle )
            continue
        return

    def _tax_context_for( self, span : DateSpan ) -> TaxContext:
        """The taxpayer context for the interval: ages from birthdates at the interval's end
        for the subjects still present, the rental properties (depreciation attributes plus any
        in-year disposition), the household's standing filing status and any spouse death year
        (the engine derives the survivor-aware effective status), and the household's subsidized
        health enrollment when coverage is in force."""
        year = span.end_date.year
        subjects = tuple(
            TaxSubject(
                handle     = subject.handle,
                age        = year - subject.birthdate.year,
                birth_year = subject.birthdate.year )
            for subject in self._parameters.active_subjects( year ) )
        return TaxContext(
            filing_status     = self._parameters.filing_status,
            spouse_death_year = self._parameters.earliest_removal_year(),
            subjects          = subjects,
            properties        = self._tax_properties_for( span ),
            health_enrollment = self._subsidized_health_enrollment_for( span ),
        )

    def _subsidized_health_enrollment_for(
            self, span : DateSpan ) -> Optional[ SubsidizedHealthEnrollment ]:
        """Resolve the household's windowed subsidized health coverage, if in force this
        interval, into the single-year `SubsidizedHealthEnrollment` the tax engine consumes
        (and, in the US, turns into the ACA premium tax credit). The household size is derived
        from the base less any subject removed by this year. None when uncovered."""
        coverage = self._parameters.health_coverage
        if ( coverage is None ) or ( not coverage.covers( span.end_date ) ):
            return None
        household_size = resolve_household_size(
            coverage.household_size, self._parameters.subject_removals, span.end_date.year )
        return SubsidizedHealthEnrollment(
            household_size    = household_size,
            reference_premium = coverage.reference_premium )

    def _tax_properties_for( self, span : DateSpan ) -> tuple:
        """The engine's `TaxProperty` for each rental: its depreciation attributes (for the
        annual deduction) plus a disposition marking the sale date when it is sold within
        this fiscal year (driving §1250 recapture). Residences need none -- their gain
        settles through the §121 residence-gains account, not the context."""
        properties = list()
        for asset, holding in self._baseline.asset_holdings:
            attributes = asset.property_attributes
            if ( asset.asset_class != AssetClass.REAL_ESTATE_RENTAL ) or ( attributes is None ):
                continue
            properties.append(
                TaxProperty(
                    holding           = holding,
                    acquisition_date  = attributes.acquisition_date,
                    depreciable_basis = attributes.depreciable_basis,
                    property_type     = attributes.property_type,
                    disposition       = self._disposition_for( asset, span ),
                )
            )
            continue
        return tuple( properties )

    def _disposition_for( self, asset, span : DateSpan ) -> Optional[ PropertyDisposition ]:
        """The disposition for `asset` if a sale of it falls in this span's fiscal year, else
        None: the first scheduled realization of its holding handle, dated in that calendar
        year. (The sale date is a scheduled input, so no running state is needed.) A property
        with no handle cannot be referenced by a sale, so it never disposes."""
        if asset.handle is None:
            return None
        fiscal_year = span.end_date.year
        for event in self._parameters.events:
            if not isinstance( event, ScheduledRealization ):
                continue
            if ( str( event.holding ) != str( asset.handle ) ) or ( event.event_date.year != fiscal_year ):
                continue
            return PropertyDisposition( sale_date = event.event_date )
        return None
