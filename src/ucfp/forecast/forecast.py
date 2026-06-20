"""The Forecast: the N-step engine above the Period.

Parallels the Period one level up -- `ForecastParameters -> Forecast -> ForecastResult`,
as `PeriodParameters -> Period -> PeriodResult`. The Forecast materializes a
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

STUB: per-period resolution covers subjects -> tax_context, AssetRates from the economic
outlook, income/expense lines from the active streams and items, and the scheduled events
occurring in the interval; the auto/feedback knobs (RMDs, adaptive conversions) join
incrementally.
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
from ucfp.period.parameters import (
    DateSpan,
    ExpenseLine,
    FundingPolicy,
    IncomeLine,
    LiabilityTerm,
    PeriodParameters,
)
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult
from ucfp.tax.law import TaxLaw
from ucfp.tax.subsidized_health import SubsidizedHealthEnrollment
from ucfp.tax.us.context import TaxContext, TaxSubject
from ucfp.tax.us.property import PropertyDisposition, TaxProperty

from .parameters import (
    ExpenseItem,
    ForecastParameters,
    ScheduledRealization,
    ScheduledWindfall,
    Subject,
)


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
    stay per-worker (the FICA cap) and Social Security per person."""

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
                )
            )
            self._account_by_key[ key ] = account
        return account


class ExpenseAccounts:
    """The expense account for each expense item (keyed by name), created on first request
    and reused after -- the one place the expense-account key lives. Per item so the Books
    keep item-level detail; each account is tagged with the item's tax-class for the engine
    to aggregate by class."""

    def __init__( self, bookkeeper : Bookkeeper ):
        self._bookkeeper = bookkeeper
        self._expense_root = bookkeeper.chart.root( AccountType.EXPENSE )
        self._account_by_name = dict()

    def account_for( self, item : ExpenseItem ) -> Account:
        """The expense account for `item`, creating it under the Expenses root on first
        request."""
        account = self._account_by_name.get( item.name )
        if account is None:
            account = self._bookkeeper.add_account(
                Account(
                    name              = item.name,
                    parent            = self._expense_root,
                    expense_tax_class = item.expense_tax_class,
                )
            )
            self._account_by_name[ item.name ] = account
        return account


class Forecast:
    """Runs a `ForecastParameters` to completion (N Period steps); see the module
    docstring for the boundary."""

    def __init__( self, parameters : ForecastParameters ):
        self._parameters = parameters
        self._tax_law    = TaxLaw( parameters.tax_forecast )
        self._income_accounts = None    # an IncomeAccounts, built with the books in _build_baseline
        self._expense_accounts = None   # an ExpenseAccounts, built with the books in _build_baseline
        self._holding_by_name = dict()  # asset name -> holding account, for resolving events
        self._draw_priority = list()    # holdings to fund from, resolved from draw_order by class
        self._loans = list()            # resolved loans (accounts + level payment), built in baseline
        self._periods_per_year = None   # set when there are liabilities (needs month/year granularity)

    def run( self ) -> ForecastResult:
        """Build the opening books from the parameters, then walk the frame running a
        Period per interval -- threading the tax state and stopping at depletion."""
        bookkeeper    = self._build_baseline()
        result        = ForecastResult( books = bookkeeper.books )
        opening_state = self._parameters.initial_tax_state
        for span in self._parameters.period_spans():
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

    def _build_baseline( self ) -> Bookkeeper:
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
            holding = bookkeeper.create_holding( asset_root, asset.name, asset.asset_class )
            holding.owner_handle = asset.owner_handle
            holdings.append( ( holding, asset.opening_value, asset.cost_basis ) )
            continue
        self._holding_by_name = {
            holding.name : holding for holding, _value, _basis in holdings }
        self._create_loans( bookkeeper )
        self._seed_opening_balances( bookkeeper, holdings )
        self._create_income_accounts( bookkeeper )
        self._create_asset_income_accounts( bookkeeper )
        self._create_windfall_income_accounts( bookkeeper )
        self._create_expense_accounts( bookkeeper )
        self._create_tax_accounts( bookkeeper )
        self._resolve_draw_priority( bookkeeper )
        return bookkeeper

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
                                 cost_basis : Decimal ) -> list:
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
            account = bookkeeper.add_account( Account( name = loan.name, parent = liability_root ) )
            interest_account = bookkeeper.add_account(
                Account( name = f'{loan.name} Interest', parent = expense_root,
                         expense_tax_class = loan.interest_class ) )
            periodic_rate = loan.interest_rate.fraction / self._periods_per_year
            periods = loan.term.months() // self._parameters.granularity.months()
            payment = _amortized_payment( loan.opening_balance, periodic_rate, periods )
            self._loans.append( _ResolvedLoan( loan, account, interest_account, payment ) )
            continue
        return

    def _create_income_accounts( self, bookkeeper : Bookkeeper ) -> None:
        """Set up the income-account registry and pre-create an account for every stream,
        so the chart is complete from the start (each stream's account exists even before
        its window opens)."""
        self._income_accounts = IncomeAccounts( bookkeeper )
        for stream in self._parameters.income_streams:
            self._income_accounts.account_for( stream.subject, stream.income_tax_class )
            continue
        return

    def _create_expense_accounts( self, bookkeeper : Bookkeeper ) -> None:
        """Set up the expense-account registry and pre-create an account for every item, so
        the chart is complete from the start."""
        self._expense_accounts = ExpenseAccounts( bookkeeper )
        for item in self._parameters.expenses:
            self._expense_accounts.account_for( item )
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

    def _create_windfall_income_accounts( self, bookkeeper : Bookkeeper ) -> None:
        """Create a revenue account for each income class a taxable windfall credits, if one
        does not already exist, so a taxable windfall has somewhere to post (non-taxable
        windfalls credit the External Receipts equity account, already in the chart)."""
        chart = bookkeeper.chart
        revenue_root = chart.root( AccountType.REVENUE )
        income_classes = {
            event.income_tax_class for event in self._parameters.events
            if isinstance( event, ScheduledWindfall ) and ( event.income_tax_class is not None ) }
        for income_class in sorted( income_classes, key = lambda klass : klass.name ):
            if chart.income_account( income_class ) is None:
                bookkeeper.add_account(
                    Account( name = income_class.label, parent = revenue_root,
                             income_tax_class = income_class ) )
            continue
        return

    def _resolve_draw_priority( self, bookkeeper : Bookkeeper ) -> None:
        """Bind the user's `draw_order` (asset classes, in priority) to the actual holding
        accounts: each class expands to its holdings (drawn sequentially), flattened into
        the order the funding waterfall draws from."""
        holdings = bookkeeper.chart.holdings()
        self._draw_priority = [
            holding for asset_class in self._parameters.draw_order
            for holding in holdings if holding.asset_class == asset_class
        ]
        return

    def _liability_terms_for( self, bookkeeper : Bookkeeper ) -> list[ LiabilityTerm ]:
        """Resolve each outstanding loan's payment for the interval from its running balance:
        interest on the balance at the periodic rate, scheduled principal = level payment -
        interest, plus the prorated extra principal -- all capped at the remaining balance so
        the final payment pays it off. A loan with no balance left is skipped."""
        ledger = bookkeeper.ledger
        terms = list()
        for loan in self._loans:
            balance = ledger.natural_balance( loan.account )
            if balance <= 0:
                continue
            interest = balance * ( loan.parameters.interest_rate.fraction / self._periods_per_year )
            principal = min( max( loan.payment - interest, Decimal( '0' ) ), balance )
            per_period_extra = loan.parameters.annual_extra_principal / self._periods_per_year
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
        """Resolve the income streams active this interval into IncomeLines: grow each to
        nominal by its class rate from the forecast start, prorate to the interval's share
        of the year, and post to its per-(subject, class) account."""
        lines = list()
        for stream in self._parameters.income_streams:
            if not stream.window.covers( span.start_date ):
                continue
            factor = self._income_growth_factor( stream.income_tax_class, span.start_date.year )
            amount = stream.annual_amount * factor * year_fraction
            account = self._income_accounts.account_for( stream.subject, stream.income_tax_class )
            lines.append( IncomeLine( account = account, gross_amount = amount ) )
            continue
        return lines

    def _expense_lines_for( self, span : DateSpan ) -> list[ ExpenseLine ]:
        """Resolve the expense items active this interval into ExpenseLines: the recurrence's
        occurrences in the interval x the per-occurrence amount in effect (inflated from the
        forecast start), posted to the item's account."""
        lines = list()
        for item in self._parameters.expenses:
            clipped = self._clip_to_window( span, item.window )
            if clipped is None:
                continue
            start, end = clipped
            since = item.window.start if item.window.start is not None else self._parameters.start_date
            occurrences = item.recurrence.count_in( start = start, end = end, since = since )
            windowed_amount = item.amounts.at( span.start_date )
            if ( occurrences == 0 ) or ( windowed_amount is None ):
                continue
            factor = self._expense_inflation_factor( item.expense_tax_class, span.start_date.year )
            account = self._expense_accounts.account_for( item )
            lines.append(
                ExpenseLine( account = account, amount = occurrences * windowed_amount.amount * factor ) )
            continue
        return lines

    def _events_for( self, span : DateSpan, bookkeeper : Bookkeeper ) -> list:
        """Resolve the scheduled events occurring in this interval into PeriodEvents, binding
        their named holdings to the running accounts via the chart (which also supplies the
        cash hub and the revenue/equity accounts a windfall credits). Order is preserved, so
        same-interval events apply as authored."""
        chart = bookkeeper.chart
        return [
            event.to_period_event( self._holding_by_name, chart )
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
        then. STUB: the remaining feedback knobs join later."""
        year_fraction = self._year_fraction( span )
        annual_rates = self._parameters.economic_outlook.asset_rates_at( span.start_date )
        return PeriodParameters(
            date_span         = span,
            tax_context       = self._tax_context_for( span ),
            asset_rates       = annual_rates.over_fraction( year_fraction ),
            income_lines      = self._income_lines_for( span, year_fraction ),
            expense_lines     = self._expense_lines_for( span ),
            liability_terms   = self._liability_terms_for( bookkeeper ),
            events            = self._events_for( span, bookkeeper ),
            funding_policy    = FundingPolicy(
                cash_target = self._parameters.cash_target, draw_priority = self._draw_priority ),
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

    def _tax_context_for( self, span : DateSpan ) -> TaxContext:
        """The taxpayer context for the interval: ages from birthdates at the interval's end,
        the rental properties (depreciation attributes plus any in-year disposition), and the
        household's subsidized health enrollment when coverage is in force. STUB: filing status
        static."""
        subjects = tuple(
            TaxSubject(
                handle     = subject.handle,
                age        = span.end_date.year - subject.birthdate.year,
                birth_year = subject.birthdate.year )
            for subject in self._parameters.subjects )
        return TaxContext(
            filing_status     = self._parameters.filing_status,
            subjects          = subjects,
            properties        = self._tax_properties_for( span ),
            health_enrollment = self._subsidized_health_enrollment_for( span ),
        )

    def _subsidized_health_enrollment_for(
            self, span : DateSpan ) -> Optional[ SubsidizedHealthEnrollment ]:
        """Resolve the household's windowed subsidized health coverage, if in force this
        interval, into the single-year `SubsidizedHealthEnrollment` the tax engine consumes
        (and, in the US, turns into the ACA premium tax credit). None when uncovered."""
        coverage = self._parameters.health_coverage
        if ( coverage is None ) or ( not coverage.covers( span.end_date ) ):
            return None
        return SubsidizedHealthEnrollment(
            household_size    = coverage.household_size,
            reference_premium = coverage.reference_premium )

    def _tax_properties_for( self, span : DateSpan ) -> tuple:
        """The engine's `TaxProperty` for each rental: its depreciation attributes (for the
        annual deduction) plus a disposition marking the sale date when it is sold within
        this fiscal year (driving §1250 recapture). Residences need none -- their gain
        settles through the §121 residence-gains account, not the context."""
        properties = list()
        for asset in self._parameters.assets:
            attributes = asset.property_attributes
            if ( asset.asset_class != AssetClass.REAL_ESTATE_RENTAL ) or ( attributes is None ):
                continue
            properties.append(
                TaxProperty(
                    holding           = self._holding_by_name[ asset.name ],
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
        None: the first scheduled realization naming the holding, dated in that calendar year.
        (The sale date is a scheduled input, so no running state is needed.)"""
        fiscal_year = span.end_date.year
        for event in self._parameters.events:
            if not isinstance( event, ScheduledRealization ):
                continue
            if ( event.holding != asset.name ) or ( event.event_date.year != fiscal_year ):
                continue
            return PropertyDisposition( sale_date = event.event_date )
        return None
