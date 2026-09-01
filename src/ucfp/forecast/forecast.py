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

It selects the tax law via the parameters' `StatuteProfile` and treats the resulting
engine as a black box: it asks the `Statute` for each year's engine and never touches a
tax knob.
"""
import calendar
from collections import namedtuple
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Optional

from common.amortization import level_payment
from common.date_span import DateSpan
from common.date_window import DateWindow
from common.rate import Rate
from ucfp.accounts.books import Account, BooksOfAccount
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.chart import Chart
from ucfp.accounts.enums import (
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
    SystemAccountRole,
)
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.accounts.ledger import Ledger
from ucfp.accounts.money_utils import format_money, quantize_money
from ucfp.period.parameters import (
    ContributionLine,
    ExpenseLine,
    FundingPolicy,
    IncomeLine,
    LiabilityTerm,
    PeriodParameters,
)
from ucfp.period.events import LoanOrigination, PeriodEvent
from ucfp.period.fiscal_window import FiscalWindow
from ucfp.period.future_tax import reestimate_future_taxes
from ucfp.period.period import Period
from ucfp.period.results import Notice, NoticeKind, NoticeSeverity, PeriodResult
from ucfp.jurisdiction.engine import ContributionKind, TaxEngine, TaxState
from ucfp.jurisdiction.law import Statute
from ucfp.jurisdiction.subsidized_health import SubsidizedHealthEnrollment
from ucfp.jurisdiction.context import TaxContext, TaxSubject
from ucfp.jurisdiction.property import TaxProperty
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.social_security_household import HouseholdMember, household_benefits

from .economic_outlook import EconomicParameters
from .parameters import (
    AssetParameters,
    ContributionSource,
    ExpenseItem,
    ExpenseStream,
    ForecastParameters,
    LoanParameters,
    ScheduledLoanPayoff,
    ScheduledPurchase,
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


# The income classes summed to report the approximate income that escaped tax in an untaxed
# partial year -- split into capital gains and ordinary. Deliberately excluded are the classes
# whose taxable amount the books cannot give without the engine's own netting/worksheets: Social
# Security (partly taxable), gross rental (net of depreciation and passive-loss limits), and
# tax-exempt interest (never taxed). SECTION_1250 recapture is engine-derived at assessment, never
# a booked posting, so it too is absent. Hence "approximate".
_CAPITAL_GAIN_CLASSES = (
    IncomeTaxClass.LONG_TERM_GAINS,
    IncomeTaxClass.SHORT_TERM_GAINS,
    IncomeTaxClass.RESIDENCE_SECTION_121_GAIN,
    IncomeTaxClass.SECOND_HOME_GAIN,
    IncomeTaxClass.RENTAL_SALE_GAIN,
    IncomeTaxClass.COLLECTIBLES_GAINS,
)
_ORDINARY_UNTAXED_CLASSES = (
    IncomeTaxClass.WAGES,
    IncomeTaxClass.ORDINARY,
    IncomeTaxClass.PENSION,
    IncomeTaxClass.RETIREMENT_DISTRIBUTION,
    IncomeTaxClass.TAXABLE_INTEREST,
    IncomeTaxClass.QUALIFIED_DIVIDENDS,
)


# A loan resolved against the books: its parameters plus the accounts and the monthly level
# payment (derived once from the opening balance and remaining months). Loans amortize monthly
# regardless of the run granularity; each interval rolls up the months it spans.
_ResolvedLoan = namedtuple(
    '_ResolvedLoan', ( 'parameters', 'account', 'interest_account', 'monthly_payment' ) )


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
    stay per-worker (the FICA cap) and Social Security per person; a None subject is household
    income (rent), an unowned account. Each account carries its subject's handle as `owner_handle`
    (None for household), so the planner associates it by `(owner, class)` -- many streams of one
    (subject, class) share the account, so it bears no own handle."""

    def __init__( self, bookkeeper : Bookkeeper ):
        self._bookkeeper = bookkeeper
        self._revenue_root = bookkeeper.chart.root( AccountType.REVENUE )
        self._account_by_key = dict()

    def account_for( self, subject : Optional[ Subject ],
                     income_tax_class : IncomeTaxClass ) -> Account:
        """The revenue account for `subject`'s `income_tax_class` income, creating it under the
        Revenue root on first request. A None subject is household income (rent) -- an unowned
        account carrying no per-worker handle."""
        key = ( subject, income_tax_class )
        account = self._account_by_key.get( key )
        if account is None:
            account = self._bookkeeper.add_account(
                Account(
                    name             = ( f'{subject.name} {income_tax_class.label}'
                                         if subject is not None else income_tax_class.label ),
                    parent           = self._revenue_root,
                    income_tax_class = income_tax_class,
                    owner_handle     = subject.handle if subject is not None else None,
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
    holding_by_handle : dict[ str, Account ]
    asset_holdings    : list[ tuple[ AssetParameters, Account ] ]
    draw_priority     : list[ Account ]
    sweep_allocation  : tuple[ tuple[ Account, Decimal ], ... ]
    loans             : list[ _ResolvedLoan ]
    income_accounts   : IncomeAccounts
    expense_accounts  : ExpenseAccounts


class BaselineBuilder:
    """Materializes a `ForecastParameters` into the opening books and the resolved structures the
    run loop reads, validating the inputs as it goes. This is the one-time build phase, kept apart
    from the time-stepping `Forecast`: `build()` runs the create/resolve/validate steps once and
    returns an immutable `ResolvedBaseline`."""

    def __init__( self, parameters : ForecastParameters, tax_law : Statute ):
        self._parameters = parameters
        self._tax_law    = tax_law
        self._income_accounts = None    # an IncomeAccounts, built with the books
        self._expense_accounts = None   # an ExpenseAccounts, built with the books
        self._holding_by_handle = dict()  # handle string -> holding account, for resolving events
        self._asset_holdings = list()   # (AssetParameters, holding) pairs, for property resolution
        self._draw_priority = list()    # holdings to fund from, resolved from draw_order by class
        self._sweep_allocation = ()     # resolved ( holding, weight ) pairs to sweep surplus into
        self._loans = list()            # resolved loans (accounts + monthly level payment)

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
        self._seed_future_tax_overlay( bookkeeper )
        return ResolvedBaseline(
            bookkeeper        = bookkeeper,
            holding_by_handle = self._holding_by_handle,
            asset_holdings    = self._asset_holdings,
            draw_priority     = self._draw_priority,
            sweep_allocation  = self._sweep_allocation,
            loans             = self._loans,
            income_accounts   = self._income_accounts,
            expense_accounts  = self._expense_accounts,
        )

    def _validate_contributions( self, bookkeeper : Bookkeeper ) -> None:
        """Check each contribution's target is a retirement holding, and that an employer match
        lands in a pre-tax account (Roth employer match is deferred) -- rejected at build so a
        mis-targeted contribution cannot silently mismodel."""
        for contribution in self._parameters.contributions:
            holding = self._holding_by_handle.get( str( contribution.account ) )
            if ( holding is None ) or ( not holding.asset_class.is_retirement_account ):
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
                f'First-year retirement contributions for "{owner}" total {format_money( total )}, over the '
                f'{format_money( limit )} annual limit.' )
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
        """Seed each holding and each loan with its *own* opening transaction, so an opening row's
        counterpart is the equity seed (Opening Balances) rather than every other opening posting.
        Every transaction is dated the day before the forecast start, so the books stand from t0;
        each balances against Opening Balances, which absorbs its residual (the cost basis or the
        loan balance -- a holding's embedded gain nets to zero against Unrealized Gains within its
        own transaction)."""
        chart            = bookkeeper.chart
        opening_balances = chart.system_account( SystemAccountRole.OPENING_BALANCES )
        opening_date     = self._parameters.start_date - timedelta( days = 1 )
        for holding, value, cost_basis in holdings:
            self._record_opening(
                bookkeeper, opening_date,
                self._opening_value_postings( chart, holding, value, cost_basis ), opening_balances,
                f'{holding.name} opening balance' )
            continue
        for loan in self._loans:
            if loan.parameters.origination_date is not None:
                continue          # originated mid-forecast: credited at its date, not seeded at t0
            self._record_opening(
                bookkeeper, opening_date,
                [ ( loan.account, loan.parameters.opening_balance ) ], opening_balances,
                f'{loan.account.name} opening balance' )
            continue
        return

    def _seed_future_tax_overlay( self, bookkeeper : Bookkeeper ) -> None:
        """Book the opening Estimated Future Taxes at t0 (the opening date), so the opening net-worth
        snapshot already reflects latent tax -- the same to-target re-estimate each period close repeats.
        Runs after every opening balance is seeded, so it reads the household's full opening position.
        Zero rates (the default) book nothing."""
        net_worth_calculation = self._parameters.net_worth_calculation
        reestimate_future_taxes(
            bookkeeper, net_worth_calculation.ordinary_tax_rate,
            net_worth_calculation.capital_gains_tax_rate, self._parameters.start_date - timedelta( days = 1 ) )
        return

    def _record_opening( self, bookkeeper : Bookkeeper, opening_date : date,
                         postings : list[ tuple[ Account, Decimal ] ],
                         opening_balances : Account, description : str ) -> None:
        """Record one account's opening `postings` as a balanced transaction (memoed by `description`),
        with Opening Balances absorbing their residual. Skips a fully-zero seed (a zero-basis holding
        contributes nothing here -- its whole value is the embedded gain, already balanced against
        Unrealized Gains)."""
        plug     = -sum( ( amount for _account, amount in postings ), Decimal( '0' ) )
        balanced = postings + [ ( opening_balances, plug ) ]
        if any( amount != 0 for _account, amount in balanced ):
            bookkeeper.record( opening_date, balanced, description = description )
        return

    def _opening_value_postings( self, chart : Chart, holding : Account, value : Decimal,
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
        """Create a liability account and an interest expense account per loan, and derive its
        monthly level payment (amortizing the opening balance over the remaining term in months).
        Loans amortize monthly at any run granularity. Called before the opening seed, which
        credits each balance."""
        if not self._parameters.loans:
            return
        liability_root = bookkeeper.chart.root( AccountType.LIABILITY )
        expense_root = bookkeeper.chart.root( AccountType.EXPENSE )
        for loan in self._parameters.loans:
            account = bookkeeper.add_account(
                Account( name = loan.name, parent = liability_root, handle = loan.handle ) )
            interest_account = bookkeeper.add_account(
                Account( name = f'{loan.name} Interest', parent = expense_root,
                         expense_tax_class = loan.interest_class, handle = loan.interest_handle ) )
            monthly_rate = loan.interest_rate.fraction / 12
            monthly_payment = level_payment( loan.opening_balance, monthly_rate, loan.term.months() )
            self._loans.append( _ResolvedLoan( loan, account, interest_account, monthly_payment ) )
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
        for entitlement in self._parameters.social_security:
            self._income_accounts.account_for( entitlement.subject, IncomeTaxClass.SOCIAL_SECURITY )
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
        """Ensure a revenue account exists for each income an asset can generate -- its yield
        (distribution) and its realized gain -- so a distribution or a funding draw's recognized gain
        has somewhere to post. Owner-attributed income (a pre-tax retirement distribution) gets a
        per-subject account in the owner's name; the rest stay household accounts keyed by class.
        Routed through the same IncomeAccounts keying as the income streams, so a given
        (subject, class) resolves to one account however it is reached."""
        subject_by_handle = { str( subject.handle ) : subject
                              for subject in self._parameters.subjects }
        for asset in self._parameters.assets:
            for income_class in ( asset.asset_class.distribution_income_class,
                                  asset.asset_class.realized_gain_income_class ):
                if income_class is None:
                    continue
                owner = ( subject_by_handle.get( str( asset.owner_handle ) )
                          if income_class.is_owner_attributed else None )
                self._income_accounts.account_for( owner, income_class )
                continue
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
            if holding.asset_class.is_retirement_account:
                raise ValueError(
                    f'Sweep destination "{handle}" is a retirement account; the sweep must invest '
                    'in taxable holdings (contribution limits are not modeled).' )
            if holding.asset_class == AssetClass.CASH:
                raise ValueError( f'Sweep destination "{handle}" is cash; it must be an investment.' )
            resolved.append( ( holding, weight ) )
            continue
        self._sweep_allocation = tuple( resolved )
        return


def _ended_at( expense, sale_date ):
    """`expense` (a stream or item) re-windowed to end at `sale_date`, keeping its start -- so the
    per-period builder stops billing it once the property is sold."""
    return replace( expense, window = DateWindow( start = expense.window.start, end = sale_date ) )


def _opened_at( expense, sale_date ):
    """A dormant expense (the post-sale rent) re-windowed to begin at `sale_date`."""
    return replace( expense, window = DateWindow( start = sale_date ) )


class Forecast:
    """Runs a `ForecastParameters` to completion (N Period steps); see the module
    docstring for the boundary."""

    def __init__( self, parameters : ForecastParameters ):
        self._parameters = parameters
        self._tax_law    = Statute( parameters.statute )
        self._baseline   = None         # the ResolvedBaseline, materialized once at the start of run()
        extra_loans, rollover_payoffs = self._expanded_recurring_loans()
        self._parameters = replace(
            self._parameters,
            loans  = self._parameters.loans + extra_loans,
            events = self._parameters.events + rollover_payoffs,
            recurring_loan_originations = list() )   # consumed here; cleared so a reuse cannot double them

    def _expanded_recurring_loans( self ) -> tuple[ list[ LoanParameters ], list[ ScheduledLoanPayoff ] ]:
        """Expand each recurring loan origination into its per-cycle loans and rollover payoffs: each
        occurrence from the forecast start on originates a fresh loan (principal inflated to its year, a
        distinct per-cycle handle) and pays off the prior cycle's loan on the same date (the traded-in
        car's loan). Done at construction, so the loans get their accounts and the existing origination and
        amortization machinery drive them unchanged."""
        loans   = list()
        payoffs = list()
        horizon = self._parameters.end_date
        start   = self._parameters.start_date
        for recurring in self._parameters.recurring_loan_originations:
            prior_handle = None
            # Skip any occurrence before the run start (as the holding path does): a vehicle whose next
            # purchase predates the chosen start neither originates a pre-start loan (which the parameters
            # reject) nor diverges from its holding.
            occurrences = [ on for on in recurring.occurrences_through( horizon ) if on >= start ]
            for cycle, occurrence in enumerate( occurrences ):
                handle    = f'{recurring.handle}:{cycle}'
                principal = recurring.principal * self._inflation_factor( occurrence.year )
                loans.append( LoanParameters(
                    name                   = recurring.name,
                    opening_balance        = principal,
                    interest_rate          = recurring.interest_rate,
                    term                   = recurring.term,
                    interest_class         = recurring.interest_class,
                    annual_extra_principal = recurring.annual_extra_principal,
                    handle                 = handle,
                    interest_handle        = f'{recurring.interest_handle}:{cycle}',
                    origination_date       = occurrence ) )
                if prior_handle is not None:
                    payoffs.append( ScheduledLoanPayoff( event_date = occurrence, loan = prior_handle ) )
                prior_handle = handle
                continue
            continue
        return loans, payoffs

    def run( self ) -> ForecastResult:
        """Build the opening books from the parameters, then walk the frame running a
        Period per interval -- threading the tax state and stopping at depletion."""
        self._baseline = BaselineBuilder( self._parameters, self._tax_law ).build()
        bookkeeper    = self._baseline.bookkeeper
        result        = ForecastResult( books = bookkeeper.books )
        opening_state = self._parameters.initial_tax_state
        # Working copies of the expenses and income the per-period builders read: a reported property sale
        # re-windows them once (see `_apply_property_sales`), so the builders stay sale-agnostic.
        self._expense_items   = list( self._parameters.expense_items )
        self._expense_streams = list( self._parameters.expense_streams )
        self._income_items    = list( self._parameters.income_items )
        self._income_streams  = list( self._parameters.income_streams )
        # Social Security is computed per interval (couple-aware) rather than pre-baked into streams; a
        # subject removal (death) drives the survivor step-up inside the calculation.
        self._government_pension = GovernmentPension( self._parameters.statute.jurisdiction_type )
        ss_deaths = { str( removal.subject_handle ): removal.event_date
                      for removal in self._parameters.subject_removals }
        self._ss_members = [
            HouseholdMember( entitlement.subject.handle, entitlement.subject.birthdate,
                             entitlement.pia_monthly, entitlement.claiming_date,
                             ss_deaths.get( str( entitlement.subject.handle ) ) )
            for entitlement in self._parameters.social_security ]
        # Whole-property sales reported by earlier periods, each ( handle, sale_date, rent_after ). Two
        # jobs: a rental sold in a prior tax YEAR is dropped from the tax context (it no longer
        # depreciates), and the sales of the CURRENT tax year that landed in earlier sub-periods are
        # threaded to the Period so it stamps their disposition at year-close -- so recapture fires the
        # same at any granularity, whether the sale and the settle share a period (yearly) or not.
        self._recorded_property_sales = list()
        for span in self._parameters.period_spans():
            if self._parameters.subjects and not self._parameters.active_subjects( span.end_date.year ):
                result.stopped_early = True
                break
            self._retitle_removed_subjects_accounts( bookkeeper, span )
            period_parameters = self._build_period_parameters( span, opening_state, bookkeeper )
            period            = Period( period_parameters )
            period_result     = period.compute( bookkeeper )
            self._flag_partial_tax_year( span, period_result, bookkeeper )
            result.steps.append( ForecastStep( span, period_result ) )
            if period_result.closing_tax_state is not None:
                opening_state = period_result.closing_tax_state
            self._apply_property_sales( period_result.property_sales )
            self._recorded_property_sales.extend( period_result.property_sales )
            if period_result.is_depleted:
                result.stopped_early = True
                break
            continue
        return result

    def _liability_terms_for( self, span : DateSpan, bookkeeper : Bookkeeper ) -> list[ LiabilityTerm ]:
        """Resolve each outstanding loan's payment for the interval by amortizing it monthly across
        the months `span` covers, then summing -- so the result is identical at any granularity (a
        year is twelve monthly steps whether run as 1x12 or 12x1). Each month books interest on the
        running balance at the monthly rate, scheduled principal = monthly payment - interest, plus
        the monthly extra principal, each capped at the remaining balance so the final payment pays
        it off. A loan with no balance left is skipped."""
        ledger = bookkeeper.ledger
        terms = list()
        for loan in self._baseline.loans:
            term = self._loan_liability_term( loan, span, ledger )
            if term is not None:
                terms.append( term )
            continue
        return terms

    def _loan_liability_term(
            self, loan : '_ResolvedLoan', span : DateSpan, ledger : Ledger ) -> Optional[ LiabilityTerm ]:
        """This span's amortization term for one loan, or None when it has no payment this span. A
        t0 loan -- or one originated in an earlier span -- amortizes its running ledger balance over
        the span's months (skipped once nothing is owed). The span a loan *originates* in amortizes
        from the declared principal rather than the ledger: the balance is credited by a
        `LoanOrigination` this same span, so it is not yet booked at build time, and only the months
        after origination amortize -- the first payment lands the month after the borrow, mirroring a
        t0 loan (funded the day before the start, first payment in month one). A loan whose
        origination is still ahead has no term."""
        origination = loan.parameters.origination_date
        if origination is not None and origination > span.end_date:
            return None                                   # not yet originated
        if origination is None or origination < span.start_date:
            opening = ledger.natural_balance( loan.account )
            if opening <= 0:
                return None                               # unseeded-and-future, or fully paid off
            return self._amortize_months( loan, opening, span.months )
        months_after = span.months - span.month_index_of( origination ) - 1
        if months_after <= 0:
            return None                                   # borrowed this span; payments start next
        return self._amortize_months( loan, loan.parameters.opening_balance, months_after )

    def _amortize_months(
            self, loan : '_ResolvedLoan', opening : Decimal, months : int ) -> LiabilityTerm:
        """Step `loan` forward `months` monthly payments from `opening`, accumulating the period's
        interest, scheduled principal, and extra principal. Each month is quantized to cents as it
        is booked -- mirroring per-month granularity exactly -- and the running balance falls by the
        quantized principal so the next month's interest is on the same balance. Stops early once
        the balance is gone (a loan that pays off mid-period)."""
        monthly_rate  = loan.parameters.interest_rate.fraction / 12
        monthly_extra = loan.parameters.annual_extra_principal / 12
        balance       = opening
        interest = principal = extra = Decimal( '0' )
        for _month in range( months ):
            if balance <= 0:
                break
            month_interest  = quantize_money( balance * monthly_rate )
            month_principal = min( quantize_money(
                max( loan.monthly_payment - month_interest, Decimal( '0' ) ) ), balance )
            month_extra     = min( quantize_money( monthly_extra ), balance - month_principal )
            interest  += month_interest
            principal += month_principal
            extra     += month_extra
            balance   -= month_principal + month_extra
            continue
        return LiabilityTerm(
            liability_account = loan.account,
            interest_account  = loan.interest_account,
            principal         = principal,
            interest          = interest,
            extra_principal   = extra,
        )

    def _income_lines_for( self, span : DateSpan, year_fraction : Decimal ) -> list[ IncomeLine ]:
        """All income IncomeLines for this interval: the smooth streams (prorated) plus the
        occurrence-based items (placed by their cadence). The income counterpart of
        `_expense_lines_for`."""
        return ( self._income_stream_lines_for( span, year_fraction )
                 + self._income_item_lines_for( span )
                 + self._social_security_lines_for( span, year_fraction ) )

    def _social_security_lines_for( self, span : DateSpan, year_fraction : Decimal ) -> list[ IncomeLine ]:
        """The couple-aware Social Security benefit for the interval, posted per subject to their SS
        account. Computed each period from the entitlement facts -- the own claim-adjusted benefit plus the
        lower earner's spousal top-up once both collect (survivor on a death, a later phase) -- then grown by
        the COLA and scaled by the funding-payable factor, exactly as the stream path grows income, and
        prorated to the interval's share of the year. Keeping the couple math and its timing here (not in
        materialization) is why Social Security is not a pre-baked stream."""
        if not self._ss_members:
            return list()
        benefits = household_benefits( self._ss_members, self._government_pension, span.start_date )
        factor   = self._income_growth_factor( IncomeTaxClass.SOCIAL_SECURITY, span.start_date.year )
        payable  = self._benefit_payable_factor( IncomeTaxClass.SOCIAL_SECURITY, span.start_date.year )
        lines = list()
        for entitlement in self._parameters.social_security:
            benefit = benefits.get( entitlement.subject.handle, Decimal( '0' ) )
            if benefit <= 0:
                continue
            account = self._baseline.income_accounts.account_for(
                entitlement.subject, IncomeTaxClass.SOCIAL_SECURITY )
            lines.append( IncomeLine(
                account = account, gross_amount = benefit * factor * payable * year_fraction,
                source = IncomeTaxClass.SOCIAL_SECURITY.label ) )
            continue
        return lines

    def _income_stream_lines_for( self, span : DateSpan, year_fraction : Decimal ) -> list[ IncomeLine ]:
        """Resolve the income streams active this interval into IncomeLines: take each stream's
        level then in effect, grow it to nominal by its class rate from the forecast start,
        prorate to the interval's share of the year, and post to its per-(subject, class) account."""
        lines = list()
        for stream in self._income_streams:
            if not stream.window.covers( span.start_date ):
                continue
            windowed_amount = stream.amounts.at( span.start_date )
            if windowed_amount is None:
                continue
            factor = self._income_growth_factor( stream.income_tax_class, span.start_date.year )
            payable = self._benefit_payable_factor( stream.income_tax_class, span.start_date.year )
            amount = windowed_amount.amount * factor * payable * year_fraction
            account = self._baseline.income_accounts.account_for( stream.subject, stream.income_tax_class )
            lines.append( IncomeLine( account = account, gross_amount = amount, source = stream.name ) )
            continue
        return lines

    def _income_item_lines_for( self, span : DateSpan ) -> list[ IncomeLine ]:
        """Resolve the occurrence-based income items active this interval into IncomeLines: the
        cadence's occurrences in the interval x the per-occurrence amount in effect (grown to
        nominal from the forecast start), posted to the per-(subject, class) account. The income
        counterpart of `_expense_item_lines_for` -- a `OneTime` cadence makes it a single receipt."""
        lines = list()
        for item in self._income_items:
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
            lines.append( IncomeLine(
                account = account, gross_amount = occurrences * windowed_amount.amount * factor,
                source = item.name ) )
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
        for item in self._expense_items:
            clipped = self._clip_to_window( span, item.window )
            if clipped is None:
                continue
            start, end = clipped
            since = self._cadence_anchor( item.cadence_anchor, item.window )
            occurrences = item.cadence.count_in( start = start, end = end, since = since )
            windowed_amount = item.amounts.at( span.start_date )
            if ( occurrences == 0 ) or ( windowed_amount is None ):
                continue
            # A fixed-in-nominal item (inflate=False) takes its entered amount as the actual dollars paid
            # each occurrence, so it does not grow with inflation; every other item grows to nominal.
            factor = ( self._expense_inflation_factor( item.expense_tax_class, span.start_date.year )
                       if item.inflate else Decimal( 1 ) )
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
        for stream in self._expense_streams:
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

    def _apply_property_sales( self, sales : list ) -> None:
        """React once to each property sale the period reported, by re-windowing the forward expense and
        income working copies: end the property's ownership costs (and its tenure-invariant utilities too
        when the household does not rent after), open its dormant rent when it does, and end any income the
        property sourced (a rental's rent, matched by `source_handle`). The expense handles come from the
        property's `PropertyData`. The per-period builders read the re-windowed copies and never learn a
        sale happened."""
        for handle, sale_date, rent_after in sales:
            data = self._parameters.property_data.get( handle )
            if data is None:
                continue
            ended = set( data.ownership_cost_handles )
            if not rent_after:
                ended |= set( data.tenure_invariant_handles )
            self._expense_streams = [ _ended_at( stream, sale_date ) if str( stream.handle ) in ended else stream
                                      for stream in self._expense_streams ]
            self._expense_items   = [ _ended_at( item, sale_date ) if str( item.handle ) in ended else item
                                      for item in self._expense_items ]
            if rent_after and data.rent_handle is not None:
                self._expense_items = [ _opened_at( item, sale_date ) if str( item.handle ) == data.rent_handle
                                        else item for item in self._expense_items ]
            self._income_streams = [ _ended_at( stream, sale_date ) if str( stream.source_handle ) == handle else stream
                                     for stream in self._income_streams ]
            self._income_items   = [ _ended_at( item, sale_date ) if str( item.source_handle ) == handle else item
                                     for item in self._income_items ]
            continue
        return

    def _events_for(
            self, span : DateSpan, year_fraction : Decimal, bookkeeper : Bookkeeper ) -> list[ PeriodEvent ]:
        """Resolve the scheduled events occurring in this interval into PeriodEvents, binding
        their holding handles to the running accounts (and via the chart the cash hub and the
        equity accounts an external receipt/disbursement moves). Order is preserved, so
        same-interval events apply as authored. The recurring realizations (scheduled withdrawals,
        Roth conversion ladders) expand into per-interval realizations appended after them."""
        chart = bookkeeper.chart
        scheduled = []
        for event in self._parameters.events:
            if not event.in_span( span ):
                continue
            period_event = event.to_period_event( self._baseline.holding_by_handle, chart )
            if period_event is not None:                 # a skipped payoff (no such loan account) drops out
                scheduled.append( period_event )
        # Originations first, so the proceeds are on the books before any same-span event that reads a
        # balance (e.g. a settle-and-re-originate cycle whose payoff must see the freshly borrowed loan).
        return ( self._loan_origination_events_for( span, chart ) + scheduled
                 + self._recurring_holding_purchase_events_for( span, chart )
                 + self._recurring_realization_events_for( span, year_fraction, chart ) )

    def _loan_origination_events_for( self, span : DateSpan, chart : Chart ) -> list[ PeriodEvent ]:
        """A `LoanOrigination` for each loan whose origination date falls in this span: it credits the
        principal to the liability and lands the proceeds in cash. The planner pairs it with the
        purchase it finances, so a financed acquisition nets to the down payment in cash. The
        amortization for the origination span is derived from the principal in `_loan_liability_term`,
        independent of this event, so the event's mid-phase timing does not affect the schedule."""
        originating = [ loan for loan in self._baseline.loans
                        if loan.parameters.origination_date is not None
                        and span.start_date <= loan.parameters.origination_date <= span.end_date ]
        if not originating:
            return list()
        cash = chart.cash_account()
        if cash is None:
            raise MissingAccountError( 'No cash account to receive loan proceeds.' )
        return [ LoanOrigination(
            event_date = loan.parameters.origination_date, liability_account = loan.account,
            cash_account = cash, principal = loan.parameters.opening_balance )
            for loan in originating ]

    def _recurring_realization_events_for(
            self, span : DateSpan, year_fraction : Decimal, chart : Chart ) -> list[ PeriodEvent ]:
        """Expand the recurring realizations active this interval into realization PeriodEvents:
        annualize the per-occurrence amount (x the interval's occurrences per year), inflate it from the
        forecast start, and prorate to the interval -- realized from the holding (to cash, or to the
        destination for a conversion). Annualized and window-gated like `_contribution_lines_for` (keep the
        two in step), so the same cadence yields the same yearly total; it emits an asset realization rather
        than a contribution line, so the realize clamp, the retirement tax, the penalty, and RMDs all apply
        as for a one-off."""
        events = list()
        for recurring in self._parameters.recurring_realizations:
            if not recurring.window.covers( span.start_date ):
                continue
            factor = self._inflation_factor( span.start_date.year )
            annual = recurring.amount * recurring.interval.occurrences_per_year()
            amount = annual * factor * year_fraction
            if amount <= 0:
                continue
            realization = ScheduledRealization(
                event_date = span.start_date, holding = recurring.holding,
                amount = amount, destination = recurring.destination )
            events.append( realization.to_period_event( self._baseline.holding_by_handle, chart ) )
            continue
        return events

    def _recurring_holding_purchase_events_for( self, span : DateSpan, chart : Chart ) -> list[ PeriodEvent ]:
        """Expand the recurring holding purchases into events for this interval: at each occurrence
        date, acquire the price inflated from the forecast start to that year, funded from cash --
        first realizing the WHOLE existing holding (the trade-in) when the purchase asks for one, its
        tax following the holding's class. A discrete lump on the occurrence's own date (a car
        replacement), unlike the annualized recurring realization; the inflation indexing lives here,
        in the engine, rather than being baked flat into the materialized inputs."""
        events = list()
        for purchase in self._parameters.recurring_holding_purchases:
            for occurrence in purchase.occurrences_in( span ):
                factor = self._inflation_factor( occurrence.year )
                if purchase.trade_in:
                    trade_in = ScheduledRealization(
                        event_date = occurrence, holding = purchase.holding, amount = None )
                    events.append( trade_in.to_period_event( self._baseline.holding_by_handle, chart ) )
                acquisition = ScheduledPurchase(
                    event_date = occurrence, asset = purchase.holding, amount = purchase.price * factor )
                events.append( acquisition.to_period_event( self._baseline.holding_by_handle, chart ) )
                continue
            continue
        return events

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

    def _cadence_anchor( self, anchor : Optional[ date ], window : DateWindow ) -> date:
        """The date a windowed item's cadence phases from: its explicit `cadence_anchor` when set (a
        fleet-wide schedule that outlives the window), else the window's own start, else the forecast
        start. Sharing an anchor across adjacent windows keeps the phase continuous, so a run cost does
        not restart -- and double-count -- at each of a vehicle's replacements."""
        if anchor is not None:
            return anchor
        return window.start if window.start is not None else self._parameters.start_date

    def _income_growth_factor( self, income_tax_class : IncomeTaxClass, target_year : int ) -> Decimal:
        return self._cumulative_factor(
            target_year, lambda segment : segment.income_growth_rate( income_tax_class ) )

    def _benefit_payable_factor( self, income_tax_class : IncomeTaxClass, target_year : int ) -> Decimal:
        """The retained share of a Social Security benefit in `target_year` under the funding-shortfall
        assumption: the outlook's `social_security_benefits_payable` once `target_year` reaches its
        `social_security_reduction_year`, else 1. A per-period step -- not a compounding rate -- applied
        alongside the COLA in `_income_stream_lines_for`; 1 for every other income class. Both knobs are
        read from the target-year outlook segment, so (as with the COLA) a multi-segment outlook keys the
        step to the segment in effect that year -- today the outlook is a single constant segment."""
        if income_tax_class is not IncomeTaxClass.SOCIAL_SECURITY:
            return Decimal( '1' )
        segment = self._parameters.economic_outlook.parameters_at( date( target_year, 1, 1 ) )
        if target_year < segment.social_security_reduction_year:
            return Decimal( '1' )
        return segment.social_security_benefits_payable.fraction

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

    def _cumulative_factor(
            self, target_year : int,
            rate_for : Callable[ [ EconomicParameters ], Rate ] ) -> Decimal:
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

    def _build_period_parameters( self, span : DateSpan, opening_tax_state : Optional[ TaxState ],
                                  bookkeeper : Bookkeeper ) -> PeriodParameters:
        """Build this interval's myopic PeriodParameters. Rates and flows are resolved to
        the interval's length (so the same parameters run at any granularity), and liability
        terms are amortized off the running balance. The tax engine is carried every interval (its
        exact real-dollar rules -- the contribution limit, the early-withdrawal penalty, forced
        RMDs -- apply regardless), but income tax settles only on a full calendar year, gated by
        `full_tax_year`."""
        year_fraction = self._year_fraction( span )
        annual_rates = self._parameters.economic_outlook.asset_rates_at( span.start_date )
        tax_engine = self._tax_law.engine_for( span.end_date.year )
        return PeriodParameters(
            date_span         = span,
            tax_context       = self._tax_context_for( span ),
            asset_rates       = annual_rates.over_fraction( year_fraction ),
            income_lines      = self._income_lines_for( span, year_fraction ),
            expense_lines     = self._expense_lines_for( span, year_fraction ),
            liability_terms   = self._liability_terms_for( span, bookkeeper ),
            contribution_lines = self._contribution_lines_for( span, year_fraction, bookkeeper ),
            events            = self._events_for( span, year_fraction, bookkeeper ),
            property_data     = self._parameters.property_data,
            prior_property_sales = tuple( self._recorded_property_sales ),
            funding_policy    = self._funding_policy_for( span ),
            tax_engine        = tax_engine,
            full_tax_year     = self._is_full_tax_year( span, tax_engine ),
            opening_tax_state = opening_tax_state,
            fiscal_window     = self._fiscal_window_for( span, bookkeeper, tax_engine ),
            property_sale_realtor_fee_rate = self._parameters.property_sale_costs.property_sale_realtor_fee_rate,
            property_sale_fixed_cost       = (
                self._parameters.property_sale_costs.property_sale_fixed_cost
                * self._inflation_factor( span.start_date.year ) ),
            latent_ordinary_tax_rate      = self._parameters.net_worth_calculation.ordinary_tax_rate,
            latent_capital_gains_tax_rate = self._parameters.net_worth_calculation.capital_gains_tax_rate,
        )

    def _year_fraction( self, span : DateSpan ) -> Decimal:
        """The interval's share of its calendar year (`days / days-in-year`), used to scale
        annual rates and income to the interval. 1 for a full calendar year; the months of
        a year sum back to 1."""
        period_days = ( span.end_date - span.start_date ).days + 1
        year_days = 366 if calendar.isleap( span.start_date.year ) else 365
        return Decimal( period_days ) / Decimal( year_days )

    def _is_full_tax_year( self, span : DateSpan, tax_engine : TaxEngine ) -> bool:
        """Whether the interval's tax year is a full calendar year within the forecast span -- the
        gate for settling income tax. A partial year (a mid-year start, or a trailing year short of
        the tax-year end) is posted but its income tax is not assessed. The engine is still carried
        every interval, so its exact, non-bracket rules (the retirement contribution limit, the
        early-withdrawal penalty, forced RMDs) keep applying to a partial year unchanged."""
        year_start, year_end = tax_engine.tax_year_bounds( span.end_date )
        return self._parameters.start_date <= year_start and self._parameters.end_date >= year_end

    def _fiscal_window_for(
            self, span : DateSpan, bookkeeper : Bookkeeper, tax_engine : TaxEngine ) -> FiscalWindow:
        """The tax-year view this interval reads: a window from the tax year's start (named by the
        engine) through the interval's end -- year-to-date, the whole year at a close. The Forecast
        owns it because the tax-year boundary is a time fact."""
        period_end = span.end_date
        year_start, _year_end = tax_engine.tax_year_bounds( period_end )
        return FiscalWindow( bookkeeper, DateSpan( year_start, period_end ) )

    def _flag_partial_tax_year(
            self, span : DateSpan, result : PeriodResult, bookkeeper : Bookkeeper ) -> None:
        """At the last interval of a partial calendar year -- the mid-year first year, or a trailing
        year ending before December 31 -- raise a Notice that tax was not computed for it (tax
        settles on whole years only). The notice carries the approximate income that escaped tax so
        the user can adjust inputs to compensate, and is a WARNING when there is any (INFO when the
        year had no readily-taxable income). Raised once, at the year's last interval; full years
        are silent."""
        end = span.end_date
        closes_calendar_year = ( end == date( end.year, 12, 31 ) ) or ( end == self._parameters.end_date )
        if not closes_calendar_year:
            return
        start = self._parameters.start_date
        starts_partial = ( end.year == start.year ) and ( ( start.month, start.day ) != ( 1, 1 ) )
        ends_partial = ( end.year == self._parameters.end_date.year ) and (
            ( self._parameters.end_date.month, self._parameters.end_date.day ) != ( 12, 31 ) )
        if not ( starts_partial or ends_partial ):
            return
        window = FiscalWindow( bookkeeper, DateSpan( date( end.year, 1, 1 ), end ) )
        gains    = sum( ( window.income( c ) for c in _CAPITAL_GAIN_CLASSES ), Decimal( '0' ) )
        ordinary = sum( ( window.income( c ) for c in _ORDINARY_UNTAXED_CLASSES ), Decimal( '0' ) )
        untaxed  = gains + ordinary
        if untaxed <= 0:
            result.notices.append( Notice(
                kind = NoticeKind.PARTIAL_YEAR_UNTAXED, severity = NoticeSeverity.INFO ) )
            return
        result.notices.append( Notice(
            kind     = NoticeKind.PARTIAL_YEAR_UNTAXED,
            severity = NoticeSeverity.WARNING,
            amount   = untaxed,
            detail   = self._untaxed_income_detail( gains, ordinary ) ) )
        return

    @staticmethod
    def _untaxed_income_detail( gains : Decimal, ordinary : Decimal ) -> str:
        """The label for the untaxed-income figure a partial-year notice carries, naming the
        capital-gain vs ordinary split when both are present so the reader can judge how to
        compensate. Amounts are whole-dollar and currency-symbol-free (the display currency is a
        presentation concern the engine does not hold); the figure is approximate by construction
        (see `_CAPITAL_GAIN_CLASSES`)."""
        if gains > 0 and ordinary > 0:
            return ( f'in approximate untaxed income '
                     f'({gains:,.0f} capital gains, {ordinary:,.0f} ordinary)' )
        if gains > 0:
            return 'in approximate untaxed capital gains'
        return 'in approximate untaxed ordinary income'

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
            reference_premium = coverage.reference_premium,
            actual_premium    = coverage.actual_premium )

    def _tax_properties_for( self, span : DateSpan ) -> tuple:
        """The engine's `TaxProperty` for each rental still held this fiscal year -- its depreciation
        attributes for the annual deduction, with `disposition=None`. A rental sold in a PRIOR tax year
        is dropped: it is no longer held, so it neither depreciates nor recaptures again. A sale
        *within* this fiscal year is not marked here -- the Period stamps the disposition from the actual
        sale it effected (see `Period._disposition_stamped_context`), so both a scheduled and a
        funding-driven sale drive §1250 recapture identically. Residences need none -- their gain
        settles through the §121 residence-gains account, not the context."""
        fiscal_year = span.end_date.year
        sold_before = { handle for handle, sale_date, _rent_after in self._recorded_property_sales
                        if sale_date.year < fiscal_year }
        properties  = list()
        for asset, holding in self._baseline.asset_holdings:
            attributes = asset.property_attributes
            if ( asset.asset_class != AssetClass.REAL_ESTATE_RENTAL ) or ( attributes is None ):
                continue
            if ( asset.handle is not None ) and ( str( asset.handle ) in sold_before ):
                continue                                   # sold in a prior tax year -> no longer held
            properties.append(
                TaxProperty(
                    holding           = holding,
                    acquisition_date  = attributes.acquisition_date,
                    depreciable_basis = attributes.depreciable_basis,
                    property_type     = attributes.property_type,
                    disposition       = None,
                )
            )
            continue
        return tuple( properties )
