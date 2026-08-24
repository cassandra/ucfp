"""Enums local to the planning-assumptions domain."""
from common.labeled_enum import LabeledEnum


class EventKind( LabeledEnum ):
    """Which kind of plan event a `PlanEvent` is -- the discriminator that selects its `EventType`
    handler in the planning layer (the references it needs, how it materializes). The handler set
    must stay in step with these members."""

    TRANSFER           = ( 'Transfer'        , 'Move money between two accounts.' )
    TAXABLE_RECEIPT    = ( 'Taxable receipt' , 'A one-time taxable receipt -- a bonus, a settlement.' )
    TAX_FREE_RECEIPT   = ( 'Tax-free receipt', 'A one-time tax-free receipt -- a gift, an inheritance.' )
    GENERAL_PAYMENT    = ( 'Payment'         , 'A non-deductible payment out (one-time or recurring).' )
    CHARITABLE_PAYMENT = ( 'Charitable gift' , 'A deductible charitable gift (one-time or recurring).' )
    MEDICAL_PAYMENT    = ( 'Medical expense' , 'A deductible medical expense (one-time or recurring).' )
    DEATH              = ( 'Death'           , "A subject's passing -- the survivor transition." )
    SELL_PROPERTY      = ( 'Sell property'   , 'Sell a home or rental property.' )
    SELL_POSSESSION    = ( 'Sell possession' , 'Sell a collectible or other possession (not a vehicle).' )
    LOAN_PAYOFF        = ( 'Loan payoff'     , 'Pay off an amortizing loan in full on a date.' )
    CARD_PAYOFF        = ( 'Card payoff'     , 'Pay off a credit-card balance in full on a date.' )


class PaymentMethod( LabeledEnum ):
    """How a vehicle purchase is paid for -- the discriminator that selects how the forecast models
    each replacement cycle. CASH buys outright, so the car is an owned, depreciating asset with no
    debt. LOAN finances the price less the down payment as a real loan originated afresh each
    replacement. LEASE pays to use the car -- a down/first payment, a monthly payment, and a
    lease-end payment -- with no ownership and no trade-in."""

    CASH  = ( 'Cash', 'Buy outright -- the car is an owned, depreciating asset.' )
    LOAN  = ( 'Loan', 'Finance the price less a down payment; a new loan each replacement.' )
    LEASE = ( 'Lease', 'Pay to use the car -- down, monthly, and lease-end payments; not owned.' )


class VehicleDispositionKind( LabeledEnum ):
    """What the household plans to do with one current owned vehicle -- the discriminator the vehicle
    plan solicits per Profile vehicle (like a debt's repayment terms), and which materialization
    dispatches. KEEP holds the car to the end of its life (it depreciates in place, no replacement) --
    its user-facing label is 'Retain', and it is the default, so the absence of a stored disposition
    means KEEP. REPLACE sells it on a date and buys a replacement that recurs thereafter. SELL sells it
    on a date with no replacement. (Leased vehicles use the sibling `LeaseDispositionKind`.)"""

    KEEP    = ( 'Retain' , 'Keep driving it to the end of its life -- no replacement.' )
    REPLACE = ( 'Replace', 'Sell it on a date and buy a replacement, recurring thereafter.' )
    SELL    = ( 'Sell'   , 'Sell it on a date, with no replacement.' )


class LeaseDispositionKind( LabeledEnum ):
    """What the household plans to do with one current *leased* vehicle at the end of its term -- the
    discriminator the vehicle plan solicits per leased vehicle, materialization dispatches. For a lease
    the choice *implies* the payment type of what follows (there is no separate payment picker): RETURN
    ends it (the current monthly runs to term end, then nothing) and is the default; RENEW signs a new
    lease and keeps leasing (a recurring lease successor); BUY_CASH and BUY_LOAN buy a vehicle at term end
    (a recurring owned purchase, paid cash or financed). RENEW/BUY_CASH/BUY_LOAN each carry a `successor`
    whose payment method is fixed by the kind. (Owned vehicles use the sibling `VehicleDispositionKind`,
    where Replace instead offers a payment switch.)"""

    RETURN   = ( 'Return', 'Let the lease expire at term end.' )
    RENEW    = ( 'Renew', 'Sign a new lease at term end and keep leasing.' )
    BUY_CASH = ( 'Buy with cash', 'Buy a vehicle at term end for cash, replacing on a schedule.' )
    BUY_LOAN = ( 'Buy with loan', 'Buy a vehicle at term end with a loan, replacing on a schedule.' )


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
