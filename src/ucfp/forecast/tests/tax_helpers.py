"""Shared tax-account helpers for the forecast tests.

Income tax is booked to a separate account per rate layer -- ordinary income, capital gains, the §1250
recapture, and collectibles gains. A test that cares about the *total* income tax sums them.
"""
from decimal import Decimal

from ucfp.accounts.enums import ExpenseTaxClass

INCOME_TAX_CLASSES = (
    ExpenseTaxClass.ORDINARY_INCOME_TAX,
    ExpenseTaxClass.CAPITAL_GAINS_TAX,
    ExpenseTaxClass.SECTION_1250_TAX,
    ExpenseTaxClass.COLLECTIBLES_TAX,
)


def income_tax_accounts( chart ):
    """The income-tax component accounts (ordinary, capital gains, §1250, collectibles)."""
    return [ chart.expense_account( tax_class ) for tax_class in INCOME_TAX_CLASSES ]


def total_income_tax( reader ):
    """The household's total income tax -- the natural balance summed across its rate-layer accounts
    (negative when a refundable credit exceeds the tax)."""
    return sum( ( reader.ledger.natural_balance( account )
                  for account in income_tax_accounts( reader.chart ) ), Decimal( '0' ) )
