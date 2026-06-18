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
from decimal import Decimal

from ucfp.accounts.enums import AccountType, ExpenseTaxClass, IncomeTaxClass
from ucfp.accounts.ledger import Ledger

from .parameters import DateSpan


class FiscalWindow:
    """One fiscal year of tax-relevant ledger facts. `income` totals the revenue
    booked to each income tax-class across the year (revenue accounts are
    credit-normal, so a window's flows are already the positive income earned)."""

    def __init__( self, ledger : Ledger, span : DateSpan ):
        self._ledger = ledger
        self._span   = span

    def income( self, income_tax_class : IncomeTaxClass ) -> Decimal:
        """Total income recognized in `income_tax_class` over the fiscal year (zero
        if no revenue account carries that class)."""
        total = Decimal( '0' )
        for account in self._ledger.accounts( account_type = AccountType.REVENUE ):
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
        for account in self._ledger.accounts( account_type = AccountType.REVENUE ):
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
        for account in self._ledger.accounts( account_type = AccountType.EXPENSE ):
            if account.expense_tax_class != expense_tax_class:
                continue
            total += self._ledger.flows(
                account, start = self._span.start_date, end = self._span.end_date )
            continue
        return -total
