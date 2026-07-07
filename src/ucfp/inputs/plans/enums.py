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
    LOAN_PAYOFF        = ( 'Loan payoff'     , 'Pay off an amortizing loan in full on a date.' )
    CARD_PAYOFF        = ( 'Card payoff'     , 'Pay off a credit-card balance in full on a date.' )


class CreditCardPlanMode( LabeledEnum ):
    """How the user plans to pay down a credit-card balance -- the strategy the debt-plan calculator
    resolves into expenses. MONTHLY pays a fixed amount each month until the card clears; BY_DATE
    derives the monthly amount that clears it by a target date; COMBO pays a fixed amount monthly,
    then clears the remaining balance in a lump on a date; LUMP carries the balance (paying interest)
    until it is paid off in full on a date. 'Just carrying it' -- paying only the interest,
    indefinitely -- is the absence of a plan, not a member."""

    MONTHLY = ( 'Pay a set amount each month', 'A fixed monthly payment until the balance clears.' )
    BY_DATE = ( 'Pay monthly to clear it by a date',
                'Pay the monthly amount that clears the balance by a target date.' )
    COMBO   = ( 'Pay monthly, then pay off the rest',
                'Pay a fixed amount monthly, then clear the remaining balance in a lump on a date.' )
    LUMP    = ( 'Pay it off in one lump', 'Carry it until you pay the whole balance on one date.' )
