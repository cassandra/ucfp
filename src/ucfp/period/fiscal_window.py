"""The fiscal-year view a TaxEngine assesses against.

A `FiscalWindow` presents one fiscal year's tax-relevant ledger facts -- income
totalled by `IncomeTaxClass` over the year's date span -- so a TaxEngine never
touches the Ledger or dates directly. The income tax it computes is an annual,
non-linear function (progressive brackets, the standard deduction, the Social
Security worksheet), so it is correct only on a *whole* fiscal year; this window is
therefore year-spanning, not period-spanning. Tax is assessed only on a *whole* calendar
year: the Forecast does not settle tax for a partial year (a mid-year start or a trailing
year short of December 31), so this window is only ever consumed for a complete year.
"""
import calendar
from datetime import timedelta
from decimal import Decimal

from common.date_span import DateSpan
from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, ExpenseTaxClass, IncomeTaxClass, SideType


class FiscalWindow:
    """One fiscal year of tax-relevant ledger facts. `income` totals the revenue
    booked to each income tax-class across the year (revenue accounts are
    credit-normal, so a window's flows are already the positive income earned)."""

    def __init__( self, bookkeeper : Bookkeeper, span : DateSpan ):
        self._chart  = bookkeeper.chart
        self._ledger = bookkeeper.ledger
        self._books  = bookkeeper.books
        self._span   = span

    @property
    def span( self ) -> DateSpan:
        """The fiscal year this window covers -- e.g. for computing a rental's
        depreciation deduction across the period."""
        return self._span

    def income( self, income_tax_class : IncomeTaxClass ) -> Decimal:
        """Total income recognized in `income_tax_class` over the fiscal year (zero
        if no revenue account carries that class)."""
        total = Decimal( '0' )
        for account in self._chart.accounts( account_type = AccountType.REVENUE ):
            if account.income_tax_class != income_tax_class:
                continue
            total += self._ledger.flows(
                account, start = self._span.start_date, end = self._span.end_date )
            continue
        return total

    def income_by_account( self, income_tax_class : IncomeTaxClass ) -> list[ Decimal ]:
        """The per-account income totals for `income_tax_class` over the fiscal year
        -- one entry per contributing revenue account. Where a class has one account
        per entity (wages: one per worker), this is the per-entity breakdown that
        FICA's per-worker Social Security cap needs; `income` sums these for income
        tax."""
        amounts = list()
        for account in self._chart.accounts( account_type = AccountType.REVENUE ):
            if account.income_tax_class != income_tax_class:
                continue
            amounts.append( self._ledger.flows(
                account, start = self._span.start_date, end = self._span.end_date ) )
            continue
        return amounts

    def expense( self, expense_tax_class : ExpenseTaxClass ) -> Decimal:
        """Total expense booked to `expense_tax_class` over the fiscal year (zero if
        no expense account carries that class). Scoped to the one class, like
        `income`; deductibility policy (which classes count, and their floors/caps)
        lives in the tax engine, not here. Expense accounts are debit-normal, so the
        window's credit-positive flows are negated to the positive amount spent."""
        total = Decimal( '0' )
        for account in self._chart.accounts( account_type = AccountType.EXPENSE ):
            if account.expense_tax_class != expense_tax_class:
                continue
            total += self._ledger.flows(
                account, start = self._span.start_date, end = self._span.end_date )
            continue
        return -total

    def holdings( self ) -> list[ Account ]:
        """The asset holdings in the books. The engine filters these to the classes a rule
        applies to (e.g. pre-tax retirement for RMDs) -- the window stays tax-agnostic."""
        return self._chart.holdings()

    def opening_value( self, holding : Account ) -> Decimal:
        """`holding`'s market value at the start of the fiscal year (its prior year-end
        balance) -- the base an RMD is sized on."""
        return self._ledger.market_value(
            holding, through = self._span.start_date - timedelta( days = 1 ) )

    def distributions_to_cash( self, holding : Account ) -> Decimal:
        """How much `holding` distributed to the cash hub over the fiscal year: the cash
        proceeds of its realizations (a transaction that draws the holding down -- credits its
        cost or valuation account -- and pays cash in). Excludes conversions to another
        holding (e.g. pre-tax -> Roth, which pays no cash) and inflows. The RMD reconciliation
        needs exactly this -- only cash distributions count toward the required minimum."""
        cash_account = self._chart.cash_account()
        if cash_account is None:
            return Decimal( '0' )
        value_accounts = { holding }
        valuation_account = self._chart.valuation_of( holding )
        if valuation_account is not None:
            value_accounts.add( valuation_account )
        total = Decimal( '0' )
        for transaction in self._books.transactions:
            if not ( self._span.start_date <= transaction.transaction_date <= self._span.end_date ):
                continue
            drawn_down = any(
                ( entry.account in value_accounts ) and ( entry.entry_direction == SideType.CREDIT )
                for entry in transaction.entries )
            if not drawn_down:
                continue
            total += sum(
                ( entry.amount for entry in transaction.entries
                  if ( entry.account is cash_account ) and ( entry.entry_direction == SideType.DEBIT ) ),
                Decimal( '0' ) )
            continue
        return total

    def contributions_from_cash( self, holding : Account ) -> Decimal:
        """How much cash was contributed into `holding` over the fiscal year: the mirror of
        `distributions_to_cash` -- a transaction that builds the holding up (debits its cost or
        valuation account) and is funded from cash (credits the cash hub). Excludes employer
        matches (funded from equity, not cash) and growth (credited to Unrealized Gains, not
        cash). Summed over the pre-tax holdings, this is the year's above-the-line deduction."""
        cash_account = self._chart.cash_account()
        if cash_account is None:
            return Decimal( '0' )
        value_accounts = { holding }
        valuation_account = self._chart.valuation_of( holding )
        if valuation_account is not None:
            value_accounts.add( valuation_account )
        total = Decimal( '0' )
        for transaction in self._books.transactions:
            if not ( self._span.start_date <= transaction.transaction_date <= self._span.end_date ):
                continue
            built_up = any(
                ( entry.account in value_accounts ) and ( entry.entry_direction == SideType.DEBIT )
                for entry in transaction.entries )
            if not built_up:
                continue
            total += sum(
                ( entry.amount for entry in transaction.entries
                  if ( entry.account is cash_account ) and ( entry.entry_direction == SideType.CREDIT ) ),
                Decimal( '0' ) )
            continue
        return total


class AnnualizedFiscalWindow:
    """A partial-year `FiscalWindow` presented at a full-year rate: every flow it reports -- income,
    deductible expense, cash contributions and distributions -- is multiplied by `factor`, the
    reciprocal of the window's share of the year, so a tax engine assessing it prices the *annualized*
    liability the year-to-date figures imply (the standard deduction and brackets, which the engine
    supplies, then apply to the grossed-up income -- the annualized-income-installment approach to
    quarterly estimated tax, simplified to calendar quarters and day-count annualization rather than
    the statute's fixed periods and factors). Point-in-time facts (the holdings and their opening
    values) are not flows and pass through unscaled. `factor` is 1 for a full-year window, so this is
    a no-op there."""

    def __init__( self, window : FiscalWindow, factor : Decimal ):
        self._window = window
        self._factor = factor

    @classmethod
    def annualizing( cls, window : FiscalWindow ) -> 'AnnualizedFiscalWindow':
        """Wrap `window` at a full-year rate: the factor is the reciprocal of the window's share of
        the calendar year. Assumes `window` spans from the tax year's start, so its inclusive day
        count is the year-to-date length -- which the estimate's year-to-date window always is."""
        year_to_date_days = ( window.span.end_date - window.span.start_date ).days + 1
        year_days = 366 if calendar.isleap( window.span.start_date.year ) else 365
        return cls( window, Decimal( year_days ) / Decimal( year_to_date_days ) )

    @property
    def span( self ) -> DateSpan:
        return self._window.span

    def income( self, income_tax_class : IncomeTaxClass ) -> Decimal:
        return self._window.income( income_tax_class ) * self._factor

    def income_by_account( self, income_tax_class : IncomeTaxClass ) -> list[ Decimal ]:
        return [ amount * self._factor for amount in self._window.income_by_account( income_tax_class ) ]

    def expense( self, expense_tax_class : ExpenseTaxClass ) -> Decimal:
        return self._window.expense( expense_tax_class ) * self._factor

    def holdings( self ) -> list[ Account ]:
        return self._window.holdings()

    def opening_value( self, holding : Account ) -> Decimal:
        return self._window.opening_value( holding )

    def distributions_to_cash( self, holding : Account ) -> Decimal:
        return self._window.distributions_to_cash( holding ) * self._factor

    def contributions_from_cash( self, holding : Account ) -> Decimal:
        return self._window.contributions_from_cash( holding ) * self._factor
