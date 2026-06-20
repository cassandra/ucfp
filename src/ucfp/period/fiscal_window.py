"""The fiscal-year view a TaxEngine assesses against.

A `FiscalWindow` presents one fiscal year's tax-relevant ledger facts -- income
totalled by `IncomeTaxClass` over the year's date span -- so a TaxEngine never
touches the Ledger or dates directly. The income tax it computes is an annual,
non-linear function (progressive brackets, the standard deduction, the Social
Security worksheet), so it is correct only on a *whole* fiscal year; this window is
therefore year-spanning, not period-spanning.

This is also the swap seam for estimated taxes: a future window that annualizes
year-to-date figures into full-year estimates plugs in here, and the engine -- which
only ever asks for annual income -- needs no change.
"""
from datetime import timedelta
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AccountType, ExpenseTaxClass, IncomeTaxClass, SideType

from .parameters import DateSpan


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

    def holdings( self ) -> tuple:
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
