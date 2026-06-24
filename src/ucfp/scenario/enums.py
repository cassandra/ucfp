"""Enums local to the planning-assumptions domain.

(`LifestyleLevel` and `LifestyleScope` live in `parameter_sets.enums` with the cost-table
payload they index, since the scenario references that library.)
"""
from common.labeled_enum import LabeledEnum


class PlannedMoveKind( LabeledEnum ):
    """Which kind of one-off balance-sheet move a `PlannedMove` is -- the engine's
    scheduled-event family."""

    TRANSFER              = ( 'Transfer', 'Move between holdings (no tax).' )
    PURCHASE              = ( 'Purchase', 'Buy a holding from cash.' )
    REALIZATION           = ( 'Realization', 'Sell/withdraw, or convert (e.g. Roth conversion).' )
    EXTERNAL_RECEIPT      = ( 'External Receipt', 'A non-taxable gift/inheritance in.' )
    EXTERNAL_DISBURSEMENT = ( 'External Disbursement', 'A non-deductible gift out.' )
