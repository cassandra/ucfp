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
outlook, and income/expense lines from the active streams and items; events and the
feedback knobs (funding draws, RMDs, adaptive conversions) join incrementally.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from common.date_window import DateWindow
from ucfp.accounts.books import Account, BooksOfAccount
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, ExpenseTaxClass, IncomeTaxClass, SystemAccountRole
from ucfp.period.parameters import DateSpan, ExpenseLine, FundingPolicy, IncomeLine, PeriodParameters
from ucfp.period.period import Period
from ucfp.period.results import PeriodResult
from ucfp.tax.law import TaxLaw
from ucfp.tax.us.context import TaxContext, TaxSubject

from .parameters import ExpenseItem, ForecastParameters, Subject


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
        self._draw_priority = list()    # holdings to fund from, resolved from draw_order by class

    def run( self ) -> ForecastResult:
        """Build the opening books from the parameters, then walk the frame running a
        Period per interval -- threading the tax state and stopping at depletion."""
        bookkeeper    = self._build_baseline()
        result        = ForecastResult( books = bookkeeper.books )
        opening_state = self._parameters.initial_tax_state
        for span in self._parameters.period_spans():
            period_parameters = self._build_period_parameters( span, opening_state )
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
        there, not handed in. One opening transaction seeds each holding's value against
        Opening Balances; revenue and expense accounts are created per income stream, per
        expense item, and per tax-payment class. STUB: holdings + income + expense + tax
        accounts; liabilities join later."""
        bookkeeper = Bookkeeper( BooksOfAccount( label = self._parameters.label ) )
        bookkeeper.build_standard_chart()
        chart = bookkeeper.chart
        asset_root = chart.root( AccountType.ASSET )
        holdings = [
            ( bookkeeper.create_holding( asset_root, asset.name, asset.asset_class ), asset.opening_value )
            for asset in self._parameters.assets ]
        opening_total = sum( ( value for _holding, value in holdings ), Decimal( '0' ) )
        if opening_total != 0:
            opening_balances = chart.system_account( SystemAccountRole.OPENING_BALANCES )
            postings = [ ( holding, -value ) for holding, value in holdings ]
            postings.append( ( opening_balances, opening_total ) )
            bookkeeper.record( self._parameters.start_date - timedelta( days = 1 ), postings )
        self._create_income_accounts( bookkeeper )
        self._create_asset_income_accounts( bookkeeper )
        self._create_expense_accounts( bookkeeper )
        self._create_tax_accounts( bookkeeper )
        self._resolve_draw_priority( bookkeeper )
        return bookkeeper

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

    def _build_period_parameters( self, span : DateSpan, opening_tax_state ) -> PeriodParameters:
        """Build this interval's myopic PeriodParameters. Rates and flows are resolved to
        the interval's length (so the same parameters run at any granularity), and tax is
        gated to the year-close interval -- the tax engine and its full-year fiscal_window
        are set only there, both None otherwise. STUB: events and feedback knobs join
        later."""
        year_fraction = self._year_fraction( span )
        annual_rates = self._parameters.economic_outlook.asset_rates_at( span.start_date )
        year_close = ( span.end_date.month == 12 ) and ( span.end_date.day == 31 )
        tax_engine = self._tax_law.engine_for( span.end_date.year ) if year_close else None
        fiscal_window = (
            DateSpan( date( span.end_date.year, 1, 1 ), span.end_date ) if year_close else None )
        return PeriodParameters(
            date_span         = span,
            tax_context       = self._tax_context_for( span ),
            asset_rates       = annual_rates.over_fraction( year_fraction ),
            income_lines      = self._income_lines_for( span, year_fraction ),
            expense_lines     = self._expense_lines_for( span ),
            funding_policy    = FundingPolicy(
                cash_target = self._parameters.cash_target, draw_priority = self._draw_priority ),
            tax_engine        = tax_engine,
            fiscal_window     = fiscal_window,
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
        """The taxpayer context for the interval: ages from birthdates at the interval's
        end. STUB: filing status static; properties/ACA not yet resolved."""
        subjects = tuple(
            TaxSubject( age = span.end_date.year - subject.birthdate.year )
            for subject in self._parameters.subjects )
        return TaxContext( filing_status = self._parameters.filing_status, subjects = subjects )
