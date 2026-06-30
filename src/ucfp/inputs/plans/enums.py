"""Enums local to the planning-assumptions domain.

(`LifestyleLevel` and `LifestyleScope` live in `parameter_sets.enums` with the cost-table
payload they index, since the plans references that library.)
"""
from common.labeled_enum import LabeledEnum


class EventKind( LabeledEnum ):
    """Which kind of plan event a `PlanEvent` is -- the discriminator that selects its `EventType`
    handler in the planning layer (the references it needs, how it materializes). The handler set
    must stay in step with these members."""

    TRANSFER           = ( 'Transfer'        , 'Move money between two accounts.' )
    ROTH_CONVERSION    = ( 'Roth conversion' , 'Convert pre-tax retirement money to Roth.' )
    TAXABLE_RECEIPT    = ( 'Taxable receipt' , 'A one-time taxable receipt -- a bonus, a settlement.' )
    TAX_FREE_RECEIPT   = ( 'Tax-free receipt', 'A one-time tax-free receipt -- a gift, an inheritance.' )
    GENERAL_PAYMENT    = ( 'Payment'         , 'A one-time non-deductible payment out.' )
    CHARITABLE_PAYMENT = ( 'Charitable gift' , 'A one-time deductible charitable gift.' )
    MEDICAL_PAYMENT    = ( 'Medical expense' , 'A one-time deductible medical expense.' )
    DEATH              = ( 'Death'           , "A subject's passing -- the survivor transition." )
    SELL_PROPERTY      = ( 'Sell property'   , 'Sell a home or rental property.' )
