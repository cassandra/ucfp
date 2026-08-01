"""The forecast's built-in assumptions -- default rates and terms the engine applies that are not
user-editable.

Consolidated as one named bundle so a new built-in assumption has an obvious home, and so both the
inputs layer (the credit-card form) and the planning engine read them from a single place. Defined
here in `inputs` -- not `planning` -- precisely so both can reach it: planning depends on inputs, and
the credit-card form is itself in inputs, so nothing needs to reach upward. The card APR travels to the
client on a `data-` attribute of the card widget (see `credit_card.py` / `inputs.js`), so no copy lives
in `AppConst`.

Distinct from the user-editable `Assumptions` aggregate (the economic outlook and tax projection):
these are values the app assumes on the user's behalf.
"""
from dataclasses import dataclass
from decimal import Decimal

from common.rate import Rate


@dataclass( frozen = True )
class BuiltinAssumptions:
    """One bundle of the forecast's non-editable, built-in assumptions."""
    credit_card_apr      : Rate
    auto_loan_apr        : Rate
    auto_loan_term_years : int


BUILTIN_ASSUMPTIONS = BuiltinAssumptions(
    credit_card_apr      = Rate.percent( Decimal( 21 ) ),
    auto_loan_apr        = Rate.percent( Decimal( '7.5' ) ),
    auto_loan_term_years = 5 )
