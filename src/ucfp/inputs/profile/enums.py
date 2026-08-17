"""Enums for the Profile (facts) domain."""
from common.labeled_enum import LabeledEnum


class HousingTenure( LabeledEnum ):
    """How the household holds its home -- a current fact, distinct from the rent amount (a plan, set
    in Spending). Owning is also carried by the residence asset; this positively marks renting and the
    rent-free case, which an asset's absence alone cannot. Renting drives the rented-home column and
    the monthly-rent row in the property-expenses matrix."""

    OWN     = ( 'Own', 'The household owns its primary residence.' )
    RENT    = ( 'Rent', 'The household rents the home it occupies.' )
    NEITHER = ( 'No housing cost',
                'No home footprint modeled: no rent, ownership costs, or utilities (housing is provided '
                'at no cost, or modeled elsewhere). Pick Rent with $0 rent if you pay any home cost.' )


class DebtKind( LabeledEnum ):
    """How a debt is treated for planning -- a user-facing classification, not an engine concept.
    Amortizing kinds (mortgage, student, personal, auto, other) are real loans that pay down on a
    schedule and sit on the balance sheet -- an *existing* auto loan is a real loan like any other
    (future car financing is modeled separately, as smoothed auto expenses). The one trigger kind,
    the credit card, is not modeled as a loan -- it drives the debt-planning interview, which turns
    it into expenses. Materialization reads `is_amortizing` to decide whether to build a loan and
    maps a mortgage's interest to its deductible tax class."""

    MORTGAGE    = ( 'Mortgage', 'A loan secured by a home; interest is deductible.' )
    STUDENT     = ( 'Student loan', 'An education loan paid down on a schedule.' )
    PERSONAL    = ( 'Personal loan', 'A general installment loan paid down on a schedule.' )
    AUTO        = ( 'Auto loan', 'An existing vehicle loan paid down on a schedule.' )
    OTHER       = ( 'Other loan', 'Any other amortizing loan.' )
    CREDIT_CARD = ( 'Credit card', 'Revolving debt; the debt plan turns it into expenses.' )

    @property
    def is_amortizing( self ) -> bool:
        """Whether this debt is modeled as a real amortizing loan (balance + rate + term, on the
        balance sheet) rather than a trigger the debt plan turns into expenses."""
        return self in _AMORTIZING_DEBT_KINDS


_AMORTIZING_DEBT_KINDS = frozenset(
    ( DebtKind.MORTGAGE, DebtKind.STUDENT, DebtKind.PERSONAL, DebtKind.AUTO, DebtKind.OTHER ) )
