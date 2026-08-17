"""Materialize a Profile + Plans + Assumptions + run frame into the engine's `ForecastParameters`.

The seam between the user-facing planning model and the Forecast engine: it composes the
facts (`Profile`), the contemplated future (`Plans`), the external factors (`Assumptions`), and the
run frame into the single `ForecastParameters` the engine consumes. It lives in `planning` -- above
the input apps and the engine -- so no input app depends on another and the engine depends on none.

Social Security composes the entitlement fact (PIA) with the claiming-age knob through the
jurisdiction-neutral `tax.government_pension` layer (the statutory schedule lives behind it,
in the jurisdiction layer, not here). Pension is materialized as its base benefit from the
chosen start date; plan-specific actuarial reduction is deferred (it is plan data, not a
general rule). Lifestyle expenses materialize per the engine's 2x2 -- smoothed categories to
expense streams, cadenced ones to placed items -- each stepping as the scheduled level changes.
"""
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from common.amortization import balance_after, level_payment, periods_to_repay, present_value
from common.date_window import DateWindow
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook
from ucfp.forecast.parameters import (
    AssetAllocation, AssetParameters, CashAccountParameters, ExpenseItem, ExpenseStream,
    ForecastParameters, IncomeItem, IncomeStream, LoanParameters, PropertyAttributes,
    RecurringHoldingPurchase, RecurringLoanOrigination, RecurringRealization, RetirementContribution,
    NetWorthCalculation, ScheduledExternalDisbursement, ScheduledRealization, Subject,
    SubsidizedHealthCoverage, TransactionCosts, WindowedAmount )

from ucfp.period.parameters import PropertyData
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.law import StatuteProfile
from ucfp.jurisdiction.us.subdivision_tax import state_tax_policy
from ucfp.planning.social_security import GovernmentPensionMember, realized_government_pensions

from ucfp.parameter_sets.enums import PropertyContext, Realization

from ucfp.planning.display_placement import (
    CAR_PAYMENTS_HANDLE, CAR_PURCHASE_HANDLE, property_expense_handle )

from ucfp.inputs.builtin_assumptions import BUILTIN_ASSUMPTIONS
from ucfp.inputs.expenses import OWNED_PROPERTY_CONTEXT
from ucfp.inputs.plans.defaults import default_drawdown
from ucfp.inputs.profile.enums import DebtKind, HousingTenure
from ucfp.inputs.profile.schemas import (
    AssetProfile, Debt, Profile, RENTED_HOME_HANDLE, ROTH_ACCOUNT_HANDLE_PREFIX )
from ucfp.inputs.plans.enums import (
    CreditCardPlanMode, PaymentMethod, VehicleDispositionKind )
from ucfp.inputs.plans.schemas import (
    CreditCardPlan, LoanRepayment, Plans, RetirementTiming, Vehicle )
from ucfp.inputs.assumptions.defaults import default_net_worth_calculation, default_transaction_costs
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.compatibility import assert_compatible
from ucfp.inputs.vehicle_handles import (
    replacement_handle, successor_handle, vehicle_holding_handle, vehicle_loan_handle,
    vehicle_loan_interest_handle )

from ucfp.inputs.events import event_contributions, vehicle_disposition_contributions


@dataclass( frozen = True )
class ForecastFrame:
    """The run configuration the engine needs that is neither a fact nor an assumption -- the
    horizon and granularity. Provided per run (often implied by the planning perspective), not
    stored in a Profile or Plans."""

    start_date  : date
    end_date    : date
    granularity : Duration = Duration( 1, TimeUnit.YEAR )


def materialize(
        profile : Profile, plans : Plans, assumptions : Assumptions,
        frame : ForecastFrame ) -> ForecastParameters:
    if profile.filing_status is None:
        raise ValueError( 'A profile must set its filing status before a forecast can run.' )
    assert_compatible( profile, plans )
    statute = _statute( profile, assumptions )
    subjects = _subjects( profile )
    subjects_by_handle = { str( subject.handle ): subject
                           for subject in subjects if subject.handle is not None }
    government_pension = GovernmentPension( statute.jurisdiction_type )
    recurring_streams, recurring_items = _recurring_expenses(
        plans, _primary_birthdate( profile ), frame )
    assets_by_handle = { asset.handle : asset for asset in profile.assets }
    events = event_contributions( profile, plans, subjects_by_handle )
    vehicle_disposition_contributions( profile, plans, events )   # derive each disposition's sale
    expense_streams, expense_items = _property_expenses(
        profile, plans, assets_by_handle, events.property_sales )
    flow_streams, flow_items = _income_flows(
        profile, plans, subjects_by_handle, events.property_sales )
    card_items, card_events = _credit_card_expenses( profile, plans, frame.start_date )
    vehicle_streams, vehicle_items = _vehicle_running_costs(
        profile, plans, events.possession_sales, frame.start_date )
    conversion_events, conversion_recurring = _roth_conversions( profile, plans )
    withdrawal_events, withdrawal_recurring = _withdrawals( profile, plans )
    scheduled_events = (
        events.scheduled_events + card_events + conversion_events + withdrawal_events )
    return ForecastParameters(
        start_date       = frame.start_date,
        end_date         = frame.end_date,
        filing_status    = profile.filing_status,
        statute          = statute,
        granularity      = frame.granularity,
        subjects         = subjects,
        assets           = _assets( profile ) + _vehicle_holdings( plans ),
        economic_outlook = _economic_outlook( assumptions ),
        income_streams   = _entitlement_income(
            profile, plans, subjects_by_handle, government_pension ) + flow_streams,
        income_items     = flow_items + events.income_items,
        expense_items    = (
            recurring_items + expense_items + events.expense_items + card_items
            + _vehicle_expenses( plans ) + _leased_current_expenses( plans, frame.start_date )
            + vehicle_items ),
        expense_streams  = recurring_streams + expense_streams + vehicle_streams,
        loans            = _loans( profile, plans ) + _current_vehicle_loans( profile, plans ),
        contributions    = _contributions( profile, plans ),
        recurring_realizations = conversion_recurring + withdrawal_recurring,
        recurring_holding_purchases = _vehicle_holding_purchases( plans ),
        recurring_loan_originations = _vehicle_loan_originations( plans ),
        events           = scheduled_events,
        property_data    = _property_data( profile, plans ),
        cash_account     = _cash_account( plans ),
        health_coverage  = _health_coverage( plans ),
        subject_removals = events.subject_removals,
        property_sale_costs = _property_sale_costs( assumptions ),
        net_worth_calculation = _net_worth_calculation( assumptions ),
    )


# --- Profile: people, balance sheet ---------------------------------------

def _subjects( profile : Profile ) -> list[ Subject ]:
    return [ Subject( name = person.name, birthdate = person.birthdate, handle = person.handle )
             for person in profile.subjects ]


def _assets( profile : Profile ) -> list[ AssetParameters ]:
    return [ _asset( asset ) for asset in profile.assets ]


def _asset( asset : AssetProfile ) -> AssetParameters:
    property_attributes = None
    if asset.property is not None:
        property_attributes = PropertyAttributes(
            acquisition_date  = asset.property.acquisition_date,
            depreciable_basis = asset.property.depreciable_basis,
            property_type     = asset.property.property_type )
    return AssetParameters(
        name = asset.name, asset_class = asset.asset_class, opening_value = asset.opening_value,
        cost_basis = _cost_basis( asset ), handle = asset.handle,
        property_attributes = property_attributes, owner_handle = asset.owner_handle )


def _cost_basis( asset : AssetProfile ) -> Decimal:
    """A zero-basis (retirement) holding seeds at 0; otherwise the stated basis, falling back
    to market value for a freshly-valued holding (cost = market)."""
    if asset.asset_class.seeds_at_zero_basis:
        return Decimal( '0' )
    if asset.cost_basis is not None:
        return asset.cost_basis
    return asset.opening_value


def _loans( profile : Profile, plans : Plans ) -> list[ LoanParameters ]:
    """The amortizing debts as engine loans, each composed from a Profile `Debt` (its current
    balance) and the Plans `LoanRepayment` that says how to repay it (rate + remaining term). A
    trigger debt (a credit card) is not `is_amortizing` and is skipped -- the debt plan, not the
    balance sheet, models it. An amortizing debt with no repayment plan yet is also skipped; it
    becomes a loan once the plan supplies its terms. A vehicle's auto loan is excluded here and
    materialized vehicle-scoped by `_current_vehicle_loans` instead."""
    repayments = { repayment.debt_handle : repayment for repayment in plans.loan_repayments }
    extra      = { prepayment.loan_handle : prepayment.annual_amount
                   for prepayment in plans.prepayments }
    assets     = { asset.handle : asset for asset in profile.assets }
    loans = []
    for debt in profile.debts:
        repayment = repayments.get( debt.handle )
        if debt.kind is DebtKind.AUTO:
            continue                                    # vehicle-scoped in `_current_vehicle_loans`
        if not debt.kind.is_amortizing or repayment is None:
            continue
        interest_class = _debt_interest_class( debt, assets.get( debt.secured_asset ) )
        loans.append(
            _loan( debt, repayment, interest_class, extra.get( debt.handle, Decimal( '0' ) ) ) )
    return loans


def _current_vehicle_loans( profile : Profile, plans : Plans ) -> list[ LoanParameters ]:
    """Each current owned vehicle's auto loan as an engine loan under its **vehicle-scoped** account
    handles (`vehicle-loan:{v}` liability + `vehicle-loan-interest:{v}` interest), composed from the
    `Debt(AUTO)` balance and the Plans `LoanRepayment` giving its rate and remaining term. Vehicle-scoped
    (not the Debt's own `{v}-loan` handle) so a current car and its future replacements group as one and
    its interest is groupable; keyed for the repayment/prepayment lookup by the Debt handle. An auto debt
    with no repayment plan yet is skipped (no terms -> no loan), as any amortizing debt would be."""
    repayments = { repayment.debt_handle : repayment for repayment in plans.loan_repayments }
    extra      = { prepayment.loan_handle : prepayment.annual_amount
                   for prepayment in plans.prepayments }
    loans = []
    for debt in profile.debts:
        repayment = repayments.get( debt.handle )
        if debt.kind is not DebtKind.AUTO or debt.secured_asset is None or repayment is None:
            continue
        loans.append( _loan(
            debt, repayment, interest_class = ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST,
            extra_principal = extra.get( debt.handle, Decimal( '0' ) ),
            handle          = vehicle_loan_handle( debt.secured_asset ),
            interest_handle = vehicle_loan_interest_handle( debt.secured_asset ) ) )
    return loans


def _loan( debt : Debt, repayment : LoanRepayment, interest_class : ExpenseTaxClass,
           extra_principal : Decimal, *, handle : Optional[ str ] = None,
           interest_handle : Optional[ str ] = None ) -> LoanParameters:
    """The engine view of an amortizing debt: its current balance is the opening balance, repaid at
    the plan's rate over its remaining term (the engine projects forward from there). A Plans
    prepayment becomes the engine's annual extra principal. `handle` / `interest_handle` override the
    account handles the loan and its interest materialize under (the vehicle loans scope theirs); by
    default the loan takes the Debt's own handle and its interest none (an unstamped fallback column)."""
    return LoanParameters(
        name = debt.name, opening_balance = debt.balance, interest_rate = repayment.interest_rate,
        term = repayment.remaining_term, interest_class = interest_class,
        annual_extra_principal = extra_principal,
        handle = handle if handle is not None else debt.handle, interest_handle = interest_handle )


def _debt_interest_class( debt : Debt, secured_asset : Optional[ AssetProfile ] ) -> ExpenseTaxClass:
    """The tax treatment of a debt's interest, by kind and (for a mortgage) what it finances: a
    rental mortgage's interest nets against rental income, a home mortgage's is an itemizable
    deduction, and every other debt kind's is non-deductible. Kept here in materialization (not on
    `DebtKind`) so the input-layer enum stays free of engine tax classes."""
    if debt.kind is not DebtKind.MORTGAGE:
        return ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST
    if secured_asset is not None and secured_asset.asset_class is AssetClass.REAL_ESTATE_RENTAL:
        return ExpenseTaxClass.RENTAL_EXPENSE
    return ExpenseTaxClass.MORTGAGE_INTEREST


# --- Plans: credit-card paydown ------------------------------------------

# The nominal APR the paydown calculator and this resolver assume. The client-side estimate reads the
# same assumption (the server renders it onto each card), so the two cannot drift.
_CREDIT_CARD_APR = BUILTIN_ASSUMPTIONS.credit_card_apr


def _credit_card_expenses(
        profile : Profile, plans : Plans,
        start : date ) -> tuple[ list[ ExpenseItem ], list[ ScheduledExternalDisbursement ] ]:
    """Every credit-card balance resolved into engine inputs at the assumed card APR. Carrying a
    balance costs its interest every month, so a card with no active paydown plan (or an explicit
    carry) becomes an indefinite interest expense; a LUMP plan carries it (interest only) until a
    date, then pays the whole balance off; MONTHLY and BY_DATE pay it down (payment covers interest
    and principal) until it clears; COMBO pays a set amount down until a date, then clears the
    remaining balance in a lump. A zero-balance card contributes nothing."""
    by_card = { plan.card_handle : plan for plan in plans.credit_card_plans }
    rate    = _CREDIT_CARD_APR.fraction / 12
    items, events = list(), list()
    for debt in profile.debts:
        if debt.kind is not DebtKind.CREDIT_CARD or debt.balance <= 0:
            continue
        _resolve_card( debt, by_card.get( debt.handle ), rate, start, items, events )
    return items, events


def _resolve_card(
        debt : Debt, plan : Optional[ CreditCardPlan ], rate : Decimal, start : date,
        items : list[ ExpenseItem ], events : list[ ScheduledExternalDisbursement ] ) -> None:
    balance = debt.balance
    mode    = plan.mode if plan is not None else None
    if mode is CreditCardPlanMode.MONTHLY:
        periods = periods_to_repay( balance, rate, plan.monthly_payment )
        end     = _months_after( start, periods ) if periods else None
        items.append( _card_expense( debt.name, 'paydown', plan.monthly_payment, end ) )
    elif mode is CreditCardPlanMode.BY_DATE:
        months = _months_between( start, plan.target_date )
        if months > 0:
            items.append( _card_expense(
                debt.name, 'paydown', level_payment( balance, rate, months ), plan.target_date ) )
    elif mode is CreditCardPlanMode.COMBO:
        _resolve_combo( debt, plan, rate, start, items, events )
    else:
        # Carrying it (no plan) or a lump payoff: pay only the interest, indefinitely for a carry, or
        # until the payoff date for a lump -- which then clears the whole (undiminished) balance.
        end = plan.target_date if mode is CreditCardPlanMode.LUMP else None
        interest = balance * rate
        if interest > 0:
            items.append( _card_expense( debt.name, 'interest', interest, end ) )
        if mode is CreditCardPlanMode.LUMP:
            events.append( ScheduledExternalDisbursement(
                event_date = plan.target_date, amount = balance ) )


def _resolve_combo(
        debt : Debt, plan : CreditCardPlan, rate : Decimal, start : date,
        items : list[ ExpenseItem ], events : list[ ScheduledExternalDisbursement ] ) -> None:
    """A COMBO plan: pay `monthly_payment` down until the target date, then clear whatever remains in
    a lump. If the monthly clears the card before the date, it is just a paydown (no lump)."""
    balance = debt.balance
    months  = _months_between( start, plan.target_date )
    if months <= 0:
        return
    cleared = periods_to_repay( balance, rate, plan.monthly_payment )
    if cleared is not None and cleared <= months:
        items.append( _card_expense(
            debt.name, 'paydown', plan.monthly_payment, _months_after( start, cleared ) ) )
        return
    items.append( _card_expense( debt.name, 'paydown', plan.monthly_payment, plan.target_date ) )
    remaining = balance_after( balance, rate, plan.monthly_payment, months )
    if remaining > 0:
        events.append(
            ScheduledExternalDisbursement( event_date = plan.target_date, amount = remaining ) )


def _card_expense( name : str, kind : str, monthly : Decimal, end : Optional[ date ] ) -> ExpenseItem:
    return ExpenseItem(
        name = f'{name} {kind}', expense_tax_class = ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST,
        amounts = Schedule.constant( WindowedAmount( monthly ) ),
        cadence = Recurrence( Duration( 1, TimeUnit.MONTH ) ), window = DateWindow( end = end ) )


def _months_between( start : date, end : date ) -> int:
    return ( end.year - start.year ) * 12 + ( end.month - start.month )


def _months_after( start : date, months : int ) -> date:
    total = start.month - 1 + months
    year  = start.year + total // 12
    month = total % 12 + 1
    return date( year, month, min( start.day, monthrange( year, month )[ 1 ] ) )


# --- Plans: vehicle (car ownership) --------------------------------------

_AUTO_LOAN_APR         = BUILTIN_ASSUMPTIONS.auto_loan_apr
_AUTO_LOAN_TERM        = Duration( BUILTIN_ASSUMPTIONS.auto_loan_term_years, TimeUnit.YEAR )
_AUTO_LOAN_TERM_MONTHS = BUILTIN_ASSUMPTIONS.auto_loan_term_months


def _is_owned( vehicle : Vehicle ) -> bool:
    """A cash or financed vehicle is owned -- a real depreciating holding that cycles on replacement. A
    leased vehicle is not owned (pure expense, no trade-in)."""
    return vehicle.payment_method in ( PaymentMethod.CASH, PaymentMethod.LOAN )


def _replacement_vehicle( disposition ) -> Vehicle:
    """The successor a Replace disposition buys, as a materializable `Vehicle`: the stored replacement
    spec with its identity and first-purchase date supplied by the disposition -- the handle derived from
    the current vehicle, the purchase date the handover date -- so it materializes exactly as a net-new
    vehicle does."""
    return replace( disposition.replacement,
                    handle = replacement_handle( disposition.vehicle_handle ),
                    purchase_date = disposition.sale_date )


def _leased_successor( disposition ) -> Vehicle:
    """The vehicle a Buy disposition purchases at lease end, as a materializable `Vehicle`: the stored
    successor spec with its identity and first date supplied by the disposition -- the handle derived from
    the leased vehicle, the purchase date the lease end -- so it materializes exactly as a net-new vehicle
    does (an owned holding that cycles on replacement)."""
    return replace( disposition.successor,
                    handle = successor_handle( disposition.vehicle_handle ),
                    purchase_date = disposition.lease_end )


def _plan_vehicles( plan ) -> list[ Vehicle ]:
    """Every vehicle the plan materializes into purchases: the net-new vehicles the household adds, each
    Replace disposition's successor, and each non-Return leased disposition's successor (the lease or
    purchase that begins at lease end -- its payment method fixed by the kind). Retain/Sell/Return add
    none -- they keep or end a current vehicle without a successor (their sale/lease expense is handled
    elsewhere). An owned Replace contributes its successor only once the whole disposition is complete --
    the successor and the sale it pairs with go together, so a half-entered Replace never sells the car
    with nothing to succeed it. A leased successor gates on its *own* readiness instead (its structural
    terms plus the lease-end it begins at); the current lease it follows is independent and materialized
    elsewhere, so an unfinished successor never suppresses the lease the household is already paying."""
    replacements = [ _replacement_vehicle( disposition ) for disposition in plan.dispositions
                     if disposition.kind is VehicleDispositionKind.REPLACE and disposition.is_complete ]
    successors   = [ _leased_successor( disposition ) for disposition in plan.leased_dispositions
                     if disposition.successor_ready ]
    return list( plan.vehicles ) + replacements + successors


def _vehicle_financed_principal( vehicle : Vehicle ) -> Decimal:
    """The amount a financed vehicle borrows each cycle -- the price less the down payment. When only the
    monthly payment was given (a no-JS entry; the calculator otherwise keeps down and monthly in step),
    the down is derived from it at the assumed rate/term. A loan with neither finances the whole price."""
    price = vehicle.purchase_price
    if vehicle.down_payment is not None:
        return max( price - vehicle.down_payment, Decimal( '0' ) )
    if vehicle.monthly_payment is not None:
        rate = _AUTO_LOAN_APR.fraction / 12
        return min( present_value( vehicle.monthly_payment, rate, _AUTO_LOAN_TERM_MONTHS ), price )
    return price


def _is_financed( vehicle : Vehicle ) -> bool:
    """A LOAN vehicle that actually borrows -- the price exceeds the down, so there is a loan to originate
    each cycle and pay off at the next trade-in. A fully-down 'loan' finances nothing and behaves like a
    cash purchase (no loan, no payoff)."""
    return vehicle.payment_method is PaymentMethod.LOAN and _vehicle_financed_principal( vehicle ) > 0


def _vehicle_holding( vehicle : Vehicle ) -> AssetParameters:
    """An owned vehicle's holding -- a DEPRECIATING asset opening at zero, filled by its purchases and
    depreciating at the class rate between them."""
    return AssetParameters(
        name = vehicle.name or 'Vehicle', asset_class = AssetClass.DEPRECIATING,
        opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ),
        handle = vehicle_holding_handle( vehicle.handle ) )


def _vehicle_holdings( plans : Plans ) -> list[ AssetParameters ]:
    """A depreciating holding for each owned (cash or financed) vehicle -- the owned car as a real asset,
    filled by its recurring purchases (`_vehicle_holding_purchases`). A leased vehicle has no holding: it
    is not owned."""
    plan = plans.vehicle_plan
    if plan is None:
        return list()
    return [ _vehicle_holding( vehicle ) for vehicle in _plan_vehicles( plan )
             if _is_owned( vehicle ) and vehicle.is_materializable ]


def _vehicle_holding_purchase( vehicle : Vehicle ) -> RecurringHoldingPurchase:
    """One owned vehicle as a recurring, inflation-indexed replacement: every `recurrence_years` over its
    window the engine trades the outgoing car in (its whole depreciated value, TAX_FREE, to cash) and
    rebuys at the price inflated to that year -- so a car bought later in the horizon costs more. Cash and
    financed cars acquire the same holding this way; a financed one adds `_vehicle_loan_originations` to
    fund it."""
    return RecurringHoldingPurchase(
        holding  = vehicle_holding_handle( vehicle.handle ),
        price    = vehicle.purchase_price,
        interval = Duration( vehicle.recurrence_years, TimeUnit.YEAR ),
        window   = DateWindow( start = vehicle.purchase_date, end = vehicle.end_date ),
        trade_in = True )


def _vehicle_holding_purchases( plans : Plans ) -> list[ RecurringHoldingPurchase ]:
    """The recurring replacement for each owned vehicle (cash or financed) -- materialization declares only
    the today's-dollars intent, and the engine owns the expansion and the inflation (it knows the horizon
    and the outlook)."""
    plan = plans.vehicle_plan
    if plan is None:
        return list()
    return [ _vehicle_holding_purchase( vehicle ) for vehicle in _plan_vehicles( plan )
             if _is_owned( vehicle ) and vehicle.is_materializable ]


def _vehicle_loan_origination( vehicle : Vehicle ) -> RecurringLoanOrigination:
    """One financed vehicle's recurring auto-loan: each replacement cycle originates a loan for the amount
    financed (price less down) at the assumed auto-loan terms, and rolls over (pays off) the outgoing car's
    loan at trade-in. The engine expands it over the horizon, inflating the principal to each cycle's year
    and appending the cycle to the handle, so the borrow offsets that cycle's (inflated) purchase and the
    two net to the down payment."""
    return RecurringLoanOrigination(
        name            = f'{vehicle.name or "Vehicle"} loan',
        principal       = _vehicle_financed_principal( vehicle ),
        interest_rate   = _AUTO_LOAN_APR,
        term            = _AUTO_LOAN_TERM,
        interval        = Duration( vehicle.recurrence_years, TimeUnit.YEAR ),
        window          = DateWindow( start = vehicle.purchase_date, end = vehicle.end_date ),
        handle          = vehicle_loan_handle( vehicle.handle ),
        interest_handle = vehicle_loan_interest_handle( vehicle.handle ) )


def _vehicle_loan_originations( plans : Plans ) -> list[ RecurringLoanOrigination ]:
    """The recurring financing for each financed vehicle -- the debt half of the owned car, paired with its
    `_vehicle_holding_purchase`. Materialization declares the recurring intent; the engine owns the cadence,
    the inflation, the per-cycle accounts, and the rollover payoff."""
    plan = plans.vehicle_plan
    if plan is None:
        return list()
    return [ _vehicle_loan_origination( vehicle ) for vehicle in _plan_vehicles( plan )
             if _is_financed( vehicle ) and vehicle.is_materializable ]


def _vehicle_expenses( plans : Plans ) -> list[ ExpenseItem ]:
    """A LEASE vehicle's cost as expense -- its down/first, monthly, and lease-end payments. CASH and LOAN
    vehicles emit nothing here: they are owned depreciating holdings (cash) financed by real recurring
    loans (loan), not an expense stream."""
    plan = plans.vehicle_plan
    if plan is None:
        return list()
    items = list()
    for vehicle in _plan_vehicles( plan ):
        if vehicle.is_materializable and vehicle.payment_method is PaymentMethod.LEASE:
            items.extend( _lease_vehicle_items( vehicle ) )
    return items


def _lease_vehicle_items( vehicle : Vehicle ) -> list[ ExpenseItem ]:
    """A leased vehicle as pure expense -- no ownership, no trade-in: the down/first payment as a lump
    each cycle, the monthly lease payment over the window, and the lease-end payment at the end of each
    lease term (one recurrence in). Blank amounts are skipped. The monthly runs continuously across the
    window, so the replacement interval is taken as the lease term (back-to-back leases); a replacement
    interval longer than the real lease term would over-charge the monthly across the gap -- the UI has one
    'replace every' field, not a separate lease term."""
    window     = DateWindow( start = vehicle.purchase_date, end = vehicle.end_date )
    recurrence = Recurrence( Duration( vehicle.recurrence_years, TimeUnit.YEAR ) )
    items = list()
    if vehicle.down_payment:
        items.append( ExpenseItem(
            name = 'Car lease', expense_tax_class = ExpenseTaxClass.LIVING,
            amounts = Schedule.constant( WindowedAmount( vehicle.down_payment ) ),
            cadence = recurrence, window = window, handle = CAR_PURCHASE_HANDLE ) )
    if vehicle.monthly_payment:
        items.append( ExpenseItem(
            name = 'Car payments', expense_tax_class = ExpenseTaxClass.LIVING,
            amounts = Schedule.constant( WindowedAmount( vehicle.monthly_payment ) ),
            cadence = Recurrence( Duration( 1, TimeUnit.MONTH ) ), window = window,
            handle = CAR_PAYMENTS_HANDLE ) )
    if vehicle.lease_end_payment:
        term_end = DateWindow(
            start = Duration( vehicle.recurrence_years, TimeUnit.YEAR ).add_to( vehicle.purchase_date ),
            end = vehicle.end_date )
        items.append( ExpenseItem(
            name = 'Car lease', expense_tax_class = ExpenseTaxClass.LIVING,
            amounts = Schedule.constant( WindowedAmount( vehicle.lease_end_payment ) ),
            cadence = recurrence, window = term_end, handle = CAR_PURCHASE_HANDLE ) )
    return items


def _lease_operates_until( disposition ) -> Optional[ date ]:
    """When a current lease stops being operated: the day before its end -- where its successor (a renewed
    lease or a purchase) begins, or where a Return simply stops -- so the two chain without a double-
    counted boundary. None (incomplete) when the end is unset."""
    if disposition.lease_end is None:
        return None
    return disposition.lease_end - timedelta( days = 1 )


def _leased_operative( disposition, start_date : date ) -> bool:
    """Whether a leased disposition's current lease materializes -- once its end is set and still ahead
    (every kind hands over or ends at that date)."""
    return disposition.lease_end is not None and disposition.lease_end > start_date


def _lease_window( disposition, start_date : date ) -> DateWindow:
    """A current lease's operating window -- from now to when it stops being operated (the horizon for a
    Renew, else the day before its end)."""
    return DateWindow( start = start_date, end = _lease_operates_until( disposition ) )


def _leased_current_expenses( plans : Plans, start_date : date ) -> list[ ExpenseItem ]:
    """The monthly cost of each current lease -- the leased twin of an owned car's holding: a leased
    vehicle is pure expense, so its current lease is a monthly item over its window (to the day before
    term end for every kind -- a Renew's continued lease and a Buy's purchase begin then, each
    materialized separately as a plan vehicle). Emitted once the current lease's monthly is set and it is
    still operative -- independent of the end-of-term plan, since the household pays the lease it holds now
    regardless of what it has decided to do at term end."""
    plan = plans.vehicle_plan
    if plan is None:
        return list()
    items = list()
    for disposition in plan.leased_dispositions:
        if disposition.monthly and _leased_operative( disposition, start_date ):
            items.append( ExpenseItem(
                name = 'Car payments', expense_tax_class = ExpenseTaxClass.LIVING,
                amounts = Schedule.constant( WindowedAmount( disposition.monthly ) ),
                cadence = Recurrence( Duration( 1, TimeUnit.MONTH ) ),
                window = _lease_window( disposition, start_date ), handle = CAR_PAYMENTS_HANDLE ) )
    return items


def _operated_until( possession : AssetProfile, sale_dates : dict ) -> Optional[ date ]:
    """The last date a current vehicle is operated: the day before its sale (so its running-cost window
    ends right where its plan replacement's begins -- both windows are inclusive and gate on the span
    start, so a shared boundary date would double-count), or None (kept -- run to the horizon)."""
    sale = sale_dates.get( possession.handle )
    return sale - timedelta( days = 1 ) if sale is not None else None


def _vehicle_windows( profile : Profile, plans : Plans, sale_dates : dict,
                      start_date : date ) -> list[ DateWindow ]:
    """The operating window of every vehicle the household runs: the current vehicle possessions (owned
    from the start, each ending when a sale clips it) and the planned vehicles (owned or leased, over
    their replacement window). Running costs apply per window, so the total tracks the fleet operated at
    any time -- a replaced current car's window ends where its plan replacement's begins, so the two
    chain with no gap and no double-count, and the near-term fleet is no longer undercounted."""
    plan    = plans.vehicle_plan
    planned = ( [ DateWindow( start = vehicle.purchase_date, end = vehicle.end_date )
                  for vehicle in _plan_vehicles( plan ) if vehicle.is_materializable ]
                if plan is not None else list() )
    current = [ DateWindow( start = start_date, end = _operated_until( possession, sale_dates ) )
                for possession in profile.assets if possession.asset_class is AssetClass.DEPRECIATING ]
    leased  = [ _lease_window( disposition, start_date )
                for disposition in ( plan.leased_dispositions if plan is not None else list() )
                if disposition.monthly and _leased_operative( disposition, start_date ) ]
    return planned + current + leased


def _vehicle_running_costs( profile : Profile, plans : Plans, sale_dates : dict,
                            start_date : date ) -> tuple[ list[ ExpenseStream ], list[ ExpenseItem ] ]:
    """The shared per-car running costs applied to each vehicle the household operates as (streams,
    items): each cost's per-car amount is emitted once per vehicle window (see `_vehicle_windows` -- the
    current possessions and the planned vehicles), so the total tracks the fleet operated over time. A
    SMOOTH cost enters as an annualized stream, a DISCRETE one as an item placed at its cadence. A
    discrete cost anchors its cadence to the forecast start (not each window's own start), so its billing
    phase is one fleet-wide schedule: a car and its replacement share it, so the changeover window is
    gated -- not re-phased -- and the transition period is never double-billed. Empty when there is no
    running cost (or it is blank)."""
    plan          = plans.vehicle_plan
    running_costs = plan.running_costs if plan is not None else list()
    windows = _vehicle_windows( profile, plans, sale_dates, start_date )
    streams, items = list(), list()
    for cost in running_costs:
        if cost.amount is None:
            continue
        amounts = Schedule.constant( WindowedAmount( cost.amount ) )
        for window in windows:
            if cost.realization is Realization.SMOOTH:
                streams.append( ExpenseStream(
                    name = cost.name, handle = cost.handle, expense_tax_class = cost.expense_tax_class,
                    amounts = _annualized( amounts, cost.interval ), window = window ) )
            else:
                items.append( ExpenseItem(
                    name = cost.name, handle = cost.handle, expense_tax_class = cost.expense_tax_class,
                    amounts = amounts, cadence = Recurrence( cost.interval ), window = window,
                    cadence_anchor = start_date ) )
    return streams, items


# --- Profile: flows (income entitlements) ----------------------------------

def _income_flows(
        profile : Profile, plans : Plans, subjects_by_handle : dict[ str, Subject ],
        sale_dates : dict ) -> tuple[ list, list ]:
    """The profile's income flows as (streams, items): a flow with no interval is a smoothed stream,
    one with an interval an item placed at that cadence (rent is monthly). The flow carries the amount
    (a Profile fact); its active window is a Plans decision (the per-flow `IncomeTiming`, keyed by the
    flow handle). `property_handle` is carried to the engine as the income's `source_handle` (rental
    income keeps its property link). A property-linked flow is clipped to its property's sale date --
    when a rental is sold, its rent stops with it (the mirror of how a property's operating expenses are
    clipped)."""
    timing = { entry.flow_handle: entry for entry in plans.income_timing }
    streams, items = list(), list()
    for flow in profile.income_flows:
        subject = ( subjects_by_handle[ flow.subject_handle ]
                    if flow.subject_handle is not None else None )   # None -> household income
        entry  = timing.get( flow.handle )
        window = DateWindow( start = entry.start, end = entry.end ) if entry is not None else DateWindow()
        amounts = _clipped_to_sale(
            Schedule( ( WindowedAmount( flow.amount, window ), ) ),
            sale_dates.get( flow.property_handle ) )
        if flow.interval is None:
            streams.append( IncomeStream(
                subject = subject, income_tax_class = flow.income_tax_class,
                amounts = amounts, source_handle = flow.property_handle, name = flow.name ) )
        else:
            items.append( IncomeItem(
                subject = subject, income_tax_class = flow.income_tax_class,
                amounts = amounts, cadence = Recurrence( flow.interval ),
                source_handle = flow.property_handle, name = flow.name ) )
    return streams, items


def _clipped_to_sale( amounts : Schedule, sale_date : Optional[ date ] ) -> Schedule:
    """`amounts` with every segment's window pulled in to `sale_date` -- so a rental's income ends when
    the property is sold. Unchanged when the property is never sold (`sale_date` None)."""
    if sale_date is None:
        return amounts
    return Schedule( tuple(
        WindowedAmount( segment.amount, _capped_window( segment.window, sale_date ) )
        for segment in amounts.segments ) )


def _capped_window( window : DateWindow, end : date ) -> DateWindow:
    """`window` with its end pulled in to `end` when it extends past it (or is unbounded)."""
    if ( window.end is None ) or ( window.end > end ):
        return DateWindow( start = window.start, end = end )
    return window


def _entitlement_income(
        profile : Profile, plans : Plans, subjects_by_handle : dict[ str, Subject ],
        government_pension : GovernmentPension ) -> list[ IncomeStream ]:
    """The retirement entitlements as realized income streams: pension and Social Security, whose
    amount and window depend on the Plans' start/claiming timing."""
    timing = { entry.subject_handle: entry for entry in plans.timing }
    streams = list()
    for pension in profile.pensions:
        streams.append( IncomeStream(
            subject = subjects_by_handle[ pension.subject_handle ],
            income_tax_class = IncomeTaxClass.PENSION,
            amounts = Schedule.constant( WindowedAmount( pension.base_annual_amount ) ),
            window = DateWindow( start = _pension_start( timing.get( pension.subject_handle ) ) ),
            name = IncomeTaxClass.PENSION.label ) )
    # Social Security is realized couple-aware (the spousal benefit couples the two subjects), so it
    # goes through the household realizer rather than a per-entitlement loop.
    for realized in realized_government_pensions(
            _government_pension_members( profile, subjects_by_handle, timing ), government_pension ):
        streams.append( IncomeStream(
            subject = subjects_by_handle[ realized.subject_handle ],
            income_tax_class = government_pension.income_tax_class(),
            amounts = realized.amounts,
            window = DateWindow( start = realized.start_date ),
            name = government_pension.income_tax_class().label ) )
    return streams


def _government_pension_members(
        profile : Profile, subjects_by_handle : dict[ str, Subject ],
        timing : dict[ str, RetirementTiming ] ) -> list[ GovernmentPensionMember ]:
    """Every household subject as a Social Security member: their entered PIA and claiming date when
    they have an entitlement, else None -- a subject with no entitlement is a potential non-earning
    spouse the realizer may top up with a spousal benefit."""
    entitlement_by_handle = {
        entitlement.subject_handle: entitlement for entitlement in profile.government_pension }
    members = list()
    for handle, subject in subjects_by_handle.items():
        entitlement  = entitlement_by_handle.get( handle )
        claim_timing = timing.get( handle )
        members.append( GovernmentPensionMember(
            subject_handle = handle,
            birthdate      = subject.birthdate,
            pia_monthly    = entitlement.monthly_at_normal_age if entitlement is not None else None,
            claiming_date  = ( claim_timing.government_pension_claiming_date
                               if claim_timing is not None else None ) ) )
    return members


def _pension_start( timing : Optional[ RetirementTiming ] ) -> Optional[ date ]:
    return timing.pension_start if timing is not None else None


def _annualized( amounts : Schedule, interval : Optional[ Duration ] ) -> Schedule:
    """A per-occurrence schedule scaled to an annual rate -- each segment's amount times the interval's
    occurrences per year -- so a SMOOTH expense enters the engine as a yearly stream level. A missing
    interval is treated as annual, leaving the amounts unchanged."""
    factor = interval.occurrences_per_year() if interval is not None else Decimal( 1 )
    return Schedule( tuple(
        WindowedAmount( segment.amount * factor, segment.window ) for segment in amounts.segments ) )


def _recurring_expenses( plans : Plans, primary_birthdate : Optional[ date ],
                         frame : 'ForecastFrame' ) -> tuple[ list, list ]:
    """The Plans' regular recurring expenses as (streams, items): each expense's per-span `amounts`
    stepped over the shared `expense_spans` timeline (until-ages relative to the primary subject,
    resolved year-precise) and clipped to the frame. A SMOOTH expense enters as an annualized stream (its
    per-occurrence amount scaled to a yearly rate); a DISCRETE one as an item placed at its cadence."""
    boundaries = _span_boundaries( plans.expense_spans, primary_birthdate )
    streams, items = list(), list()
    for expense in plans.recurring_expenses:
        amounts = _span_schedule( expense.amounts, boundaries, frame )
        if expense.realization is Realization.SMOOTH:
            streams.append( ExpenseStream(
                name = expense.name, handle = expense.handle, expense_tax_class = expense.expense_tax_class,
                amounts = _annualized( amounts, expense.interval ) ) )
        else:
            items.append( ExpenseItem(
                name = expense.name, handle = expense.handle, expense_tax_class = expense.expense_tax_class,
                amounts = amounts, cadence = Recurrence( expense.interval ) ) )
    return streams, items


def _span_boundaries( spans : list, primary_birthdate : Optional[ date ] ) -> list:
    """The finite span boundaries (the `until_age`s of `expense_spans`) resolved to dates -- the year
    the primary reaches each age. Empty when ages cannot resolve (no primary birthdate), so the whole
    forecast is one span."""
    if primary_birthdate is None:
        return list()
    return [ _at_year( primary_birthdate, age ) for age in spans if age is not None ]


def _span_schedule( amounts : list, boundaries : list, frame : 'ForecastFrame' ) -> Schedule:
    """A `Schedule[WindowedAmount]` stepping `amounts` over the spans the `boundaries` (span end dates,
    ascending) carve the frame into: `amounts[i]` applies until `boundaries[i]`, the last amount to the
    frame end. Windows are clipped to the frame, so a span the frame excludes contributes nothing;
    `amounts` is padded to the span count (a desynced document cannot crash a run)."""
    span_count = len( boundaries ) + 1
    segments   = list()
    previous   = frame.start_date
    for index in range( span_count ):
        boundary = boundaries[ index ] if index < len( boundaries ) else None
        window_start = max( previous, frame.start_date )
        window_end   = min( ( boundary - timedelta( days = 1 ) ) if boundary is not None
                            else frame.end_date, frame.end_date )
        amount = amounts[ index ] if index < len( amounts ) else (
            amounts[ -1 ] if amounts else Decimal( '0' ) )
        if window_start <= window_end:
            segments.append( WindowedAmount(
                amount, DateWindow( start = window_start, end = window_end ) ) )
        if boundary is not None:
            previous = boundary
    return Schedule( tuple( segments ) )


def _at_year( birthdate : date, age : int ) -> date:
    """The date the person turns `age` -- their birthday that year (year-precise; long-term forecasting
    needs no month precision)."""
    try:
        return birthdate.replace( year = birthdate.year + age )
    except ValueError:                                     # 29 Feb in a non-leap target year
        return birthdate.replace( year = birthdate.year + age, day = 28 )


def _primary_birthdate( profile : Profile ) -> Optional[ date ]:
    """The primary subject's birthdate (the household's first person), or None if none is set yet --
    the anchor the recurring-expense span ages resolve against."""
    return profile.subjects[ 0 ].birthdate if profile.subjects else None


def _property_contexts( profile : Profile ) -> list:
    """(handle, context, asset) for each property the household has -- owned dwellings, then the tenant's
    rented home (no owned asset) -- so a property expense can be applied by context. The owned-class ->
    context map is the same one the Home Expenses matrix keys on, imported so it has one owner."""
    result = [ ( asset.handle, OWNED_PROPERTY_CONTEXT[ asset.asset_class ], asset )
               for asset in profile.assets if asset.asset_class in OWNED_PROPERTY_CONTEXT ]
    if profile.home_tenure is HousingTenure.RENT:
        result.append( ( RENTED_HOME_HANDLE, PropertyContext.RENTED_HOME, None ) )
    return result


_RENT_HANDLE = 'rent'


def _residence_handle( profile : Profile ) -> Optional[ str ]:
    """The primary residence's handle, or None if the household owns none."""
    for asset in profile.assets:
        if asset.asset_class is AssetClass.REAL_ESTATE_RESIDENCE:
            return str( asset.handle )
    return None


def _rent_account_handle( plans : Plans ) -> Optional[ str ]:
    """The account handle of the post-sale rent, or None when there is no rent row or amount. The rent row
    is seeded into `plans.property_expenses` at the catalog default whenever the household has a home."""
    rent = next( ( e for e in plans.property_expenses if e.handle == _RENT_HANDLE ), None )
    if rent is None or not rent.default_amount:
        return None
    return str( property_expense_handle( _RENT_HANDLE, RENTED_HOME_HANDLE ) )


def _dormant_rent( plans : Plans ) -> Optional[ ExpenseItem ]:
    """The post-residence-sale rent as a *dormant* item: the stored rent row's amount, class, and cadence,
    windowed never to fire until the forecast opens it at the residence sale (however triggered). Its
    `default_amount` is the source -- the user's figure, or the catalog default when untouched. None when
    there is no rent row or amount."""
    rent = next( ( e for e in plans.property_expenses if e.handle == _RENT_HANDLE ), None )
    if rent is None or not rent.default_amount:
        return None
    return ExpenseItem(
        name              = 'Rented Home Rent',
        handle            = property_expense_handle( _RENT_HANDLE, RENTED_HOME_HANDLE ),
        expense_tax_class = rent.expense_tax_class,
        amounts           = Schedule( ( WindowedAmount( rent.default_amount, DateWindow() ), ) ),
        cadence           = Recurrence( rent.interval ),
        window            = DateWindow( start = date.max ) )   # dormant until the sale reconfiguration opens it


def _residence_expense_handles( plans : Plans, residence_handle : str ) -> tuple[ tuple, tuple ]:
    """(ownership_cost_handles, tenure_invariant_handles) for the residence: the account handles of its
    materialized property expenses, split by whether each carries into a rental (utilities) or ends with
    ownership (property tax, upkeep). The handles the forecast ends at a residence sale -- keeping the
    invariant ones only when the household rents after."""
    ownership, invariant = list(), list()
    for expense in plans.property_expenses:
        if PropertyContext.RESIDENCE not in expense.applies_to:
            continue
        if not expense.overrides.get( residence_handle, expense.default_amount ):
            continue
        handle = str( property_expense_handle( expense.handle, residence_handle ) )
        ( invariant if expense.tenure_invariant else ownership ).append( handle )
    return tuple( ownership ), tuple( invariant )


def _property_expenses( profile : Profile, plans : Plans, assets : dict, sale_dates : dict ) -> tuple[ list, list ]:
    """The Plans' property operating expenses as (streams, items): each expense applied to every property
    its `applies_to` reaches, at that property's override or the shared default (skipped when both are
    blank or zero), with the tax class derived from the property and the amount capped to the property's
    ownership window -- its sale date, when it is sold. Each account is scoped to its property (name
    prefixed with the property) so a rental's cost -- taxed as a rental expense -- stays distinct from
    the residence's same-named cost. A SMOOTH expense enters as an annualized stream; a DISCRETE one as an
    item placed at its cadence.

    The primary residence is *not* clipped here: its sale is books-driven, so the forecast ends its costs
    (and opens the rent) when the sale is reported, however it is triggered. Other sold properties (a second
    home, a rental) still clip at their fixed sale date. A residence-owning household also gets a dormant
    rent item -- inactive until that post-sale reconfiguration opens it."""
    residence_handle = _residence_handle( profile )
    streams, items = list(), list()
    for expense in plans.property_expenses:
        for handle, context, asset in _property_contexts( profile ):
            if context not in expense.applies_to:
                continue
            amount = expense.overrides.get( handle, expense.default_amount )
            if not amount:
                continue
            sale_date = None if handle == residence_handle else sale_dates.get( handle )
            tax_class      = _property_expense_tax_class( expense, asset )
            amounts        = _property_schedule( amount, sale_date )
            name           = _property_expense_name( asset, expense )
            account_handle = property_expense_handle( expense.handle, handle )
            if expense.realization is Realization.SMOOTH:
                streams.append( ExpenseStream(
                    name = name, handle = account_handle, expense_tax_class = tax_class,
                    amounts = _annualized( amounts, expense.interval ) ) )
            else:
                items.append( ExpenseItem(
                    name = name, handle = account_handle, expense_tax_class = tax_class,
                    amounts = amounts, cadence = Recurrence( expense.interval ) ) )
    if residence_handle is not None:
        rent = _dormant_rent( plans )
        if rent is not None:
            items.append( rent )
    return streams, items


def _property_expense_name( asset : Optional[ AssetProfile ], expense ) -> str:
    """A property expense's account name, scoped to its property so each property's costs are a distinct
    account -- their per-property tax class is not lost to a same-named sibling, and the results show
    each property's costs on their own line. The owned property's name (or the rented-home label) leads
    the expense name."""
    label = asset.name if asset is not None else 'Rented Home'
    return f'{label} {expense.name}'


def _property_schedule( amount : Decimal, sale_date ) -> Schedule:
    """A constant `amount` over the property's ownership window -- the whole forecast, or capped at its
    sale date when it is sold."""
    window = DateWindow( end = sale_date ) if sale_date is not None else DateWindow()
    return Schedule( ( WindowedAmount( amount, window ), ) )


def _property_expense_tax_class( expense, asset : Optional[ AssetProfile ] ) -> ExpenseTaxClass:
    """The tax treatment of a property-scoped expense: on a rental it is a rental expense (netted
    against the rent), otherwise the flow's stored personal class (`LIVING`, or `SALT` for property
    tax -- capped in aggregate). A household flow (no property, `asset` None) keeps its stored class.
    The mirror of `_debt_interest_class`: a property-linked flow's class is derived from the property,
    not stored, so both live here in materialization."""
    if asset is not None and asset.asset_class is AssetClass.REAL_ESTATE_RENTAL:
        return ExpenseTaxClass.RENTAL_EXPENSE
    return expense.expense_tax_class


# --- Plans: knobs -------------------------------------------------------

def _contributions( profile : Profile, plans : Plans ) -> list[ RetirementContribution ]:
    """The Plans' retirement contributions as engine contributions. Each is annualized (its
    per-occurrence amount x the cadence's occurrences per year) into the engine's annual, wage-grown
    `RetirementContribution`, over the owner's age window resolved to dates. The account owner's birthdate
    anchors the ages; a contribution to an unowned/unknown account simply runs unbounded (non-blocking)."""
    owner_birthdates = _owner_birthdates( profile )
    contributions = list()
    for contribution in plans.contributions:
        birthdate = owner_birthdates.get( contribution.account_handle )
        annual    = contribution.amount * contribution.interval.occurrences_per_year()
        contributions.append( RetirementContribution(
            account = contribution.account_handle, amount = annual, source = contribution.source,
            window = _age_window( contribution.start_age, contribution.end_age, birthdate ) ) )
        continue
    return contributions


def _roth_conversions( profile : Profile, plans : Plans ) -> tuple[ list, list ]:
    """The Plans' Roth conversions as (single-date realizations, recurring realizations). Each converts a
    pre-tax account to its owner's Roth (always present), inflation-indexed. A conversion whose owner or
    Roth cannot be resolved is skipped."""
    owner_birthdates = _owner_birthdates( profile )
    owner_of         = { asset.handle : asset.owner_handle for asset in profile.assets }
    handles          = { asset.handle for asset in profile.assets }
    scheduled, recurring = list(), list()
    for conversion in plans.roth_conversions:
        owner  = owner_of.get( conversion.source_handle )
        target = f'{ROTH_ACCOUNT_HANDLE_PREFIX}{owner}' if owner is not None else None
        if target is None or target not in handles:
            continue
        _planned_realization(
            conversion, target, owner_birthdates.get( conversion.source_handle ), scheduled, recurring )
        continue
    return scheduled, recurring


def _withdrawals( profile : Profile, plans : Plans ) -> tuple[ list, list ]:
    """The Plans' scheduled withdrawals as (single-date realizations, recurring realizations) -- deliberate
    draws from a pre-tax retirement account to cash (destination None), landing in cash in the accrual
    phase before the automatic cash-management drawdown. The draw is ordinary income (plus any penalty or
    RMD); a withdrawal from an unknown account is skipped."""
    owner_birthdates = _owner_birthdates( profile )
    handles          = { asset.handle for asset in profile.assets }
    scheduled, recurring = list(), list()
    for withdrawal in plans.withdrawals:
        if withdrawal.source_handle not in handles:
            continue
        _planned_realization(
            withdrawal, None, owner_birthdates.get( withdrawal.source_handle ), scheduled, recurring )
        continue
    return scheduled, recurring


def _planned_realization( plan, destination, birthdate, scheduled : list, recurring : list ) -> None:
    """Dispatch one planned realization (a conversion or withdrawal -- `source_handle`, `amount`,
    `interval`, `start_age`, `end_age`) into `scheduled` or `recurring`: a one-time plan (no `interval`) is
    a single `ScheduledRealization` at the owner's `start_age`, a recurring one a `RecurringRealization`
    over the owner's age window. `destination` is the Roth handle for a conversion, None (-> cash) for a
    withdrawal."""
    if plan.interval is None:
        on = ( _at_year( birthdate, plan.start_age )
               if birthdate is not None and plan.start_age is not None else None )
        if on is not None:
            scheduled.append( ScheduledRealization(
                event_date = on, holding = plan.source_handle, amount = plan.amount,
                destination = destination ) )
    else:
        recurring.append( RecurringRealization(
            holding = plan.source_handle, amount = plan.amount, interval = plan.interval,
            window = _age_window( plan.start_age, plan.end_age, birthdate ), destination = destination ) )


def _owner_birthdates( profile : Profile ) -> dict:
    """account handle -> its owner's birthdate, for the accounts that have an owner (retirement holdings
    are individual). Unowned accounts are absent, so their contributions resolve to no age bound."""
    by_subject = { subject.handle : subject.birthdate for subject in profile.subjects }
    return { asset.handle : by_subject[ asset.owner_handle ]
             for asset in profile.assets
             if asset.owner_handle is not None and asset.owner_handle in by_subject }


def _age_window( start_age, end_age, birthdate : Optional[ date ] ) -> DateWindow:
    """A [start_age, end_age] pair as a date window against `birthdate` -- each bound present only when
    both its age and the birthdate are known, else left open (no bound)."""
    start = _at_year( birthdate, start_age ) if start_age is not None and birthdate is not None else None
    end = _at_year( birthdate, end_age ) if end_age is not None and birthdate is not None else None
    return DateWindow( start = start, end = end )


def _cash_account( plans : Plans ) -> CashAccountParameters:
    drawdown = plans.drawdown or default_drawdown()   # the sensible band applies even for an unedited plan
    sweep = AssetAllocation( tuple( drawdown.sweep_allocation ) ) if drawdown.sweep_allocation else None
    # Only the enabled sources reach the engine; a retained one is dropped here, so the engine iterates a
    # waterfall that never mentions it. Retained keeps its slot in `draw_order`, so priority is preserved.
    retained  = set( drawdown.retained )
    draw_order = [ source for source in drawdown.draw_order if source not in retained ]
    return CashAccountParameters(
        cash_floor = drawdown.cash_floor, cash_ceiling = drawdown.cash_ceiling,
        draw_order = draw_order, sweep_allocation = sweep )


def _property_data( profile : Profile, plans : Plans ) -> dict:
    """One `PropertyData` per owned real-estate property, keyed by the property's handle -- the passive
    bundle a sale (scheduled or shortfall-driven) reaches. Carries the mortgage account handles the sale
    pays off: an amortizing, non-vehicle debt with a repayment plan (matching `_loans`), materialized under
    its Debt's own handle (per `_loan`), so it names only loans that actually reach the books. The post-sale
    expense fields are populated for the residence in a later step; every property gets an entry so the sale
    routine always finds one, even a property with no mortgage."""
    repayments  = { repayment.debt_handle for repayment in plans.loan_repayments }
    real_estate = [ asset.handle for asset in profile.assets if asset.asset_class.is_real_estate ]
    mortgages : dict = dict()
    for debt in profile.debts:
        if debt.kind is DebtKind.AUTO or not debt.kind.is_amortizing:
            continue
        if debt.secured_asset not in real_estate or debt.handle not in repayments:
            continue
        mortgages.setdefault( str( debt.secured_asset ), list() ).append( str( debt.handle ) )
    residence_handle = _residence_handle( profile )
    data : dict = dict()
    for handle in real_estate:
        mortgage_handles = tuple( mortgages.get( str( handle ), () ) )
        if str( handle ) == residence_handle:
            ownership, invariant = _residence_expense_handles( plans, residence_handle )
            data[ str( handle ) ] = PropertyData(
                mortgage_handles = mortgage_handles, ownership_cost_handles = ownership,
                tenure_invariant_handles = invariant, rent_handle = _rent_account_handle( plans ) )
        else:
            data[ str( handle ) ] = PropertyData( mortgage_handles = mortgage_handles )
    return data


def _health_coverage( plans : Plans ) -> Optional[ SubsidizedHealthCoverage ]:
    coverage = plans.health_coverage
    if coverage is None:
        return None
    # An unset actual premium means "assume the benchmark plan", so the credit's actual-premium cap
    # does not bind until the user names a cheaper plan.
    actual_premium = ( coverage.actual_premium
                       if coverage.actual_premium is not None else coverage.reference_premium )
    return SubsidizedHealthCoverage(
        window = DateWindow( start = coverage.start, end = coverage.through ),
        household_size = coverage.household_size, reference_premium = coverage.reference_premium,
        actual_premium = actual_premium )


# --- Assumptions: external factors (reuse engine types; no zero-fill) ---------

def _economic_outlook( assumptions : Assumptions ) -> EconomicOutlook:
    """The assumptions' own economic-factors copy as the engine's outlook -- a constant outlook for
    now. The copy is seeded from a library preset at input time, so there is no library load here."""
    if assumptions.economics is None:
        raise ValueError( 'Assumptions must carry economic factors (seed them from a preset).' )
    return EconomicOutlook.constant( assumptions.economics )


def _property_sale_costs( assumptions : Assumptions ) -> TransactionCosts:
    """The selling costs the engine applies to a property sale -- the assumptions' own copy, or the
    shared default when unset."""
    return assumptions.transaction_costs or default_transaction_costs()


def _net_worth_calculation( assumptions : Assumptions ) -> NetWorthCalculation:
    """The net-worth calculation the engine applies -- the latent-tax overlay rates from the
    assumptions' own copy, or the zero-rate (overlay-off) default when unset."""
    return assumptions.net_worth or default_net_worth_calculation()


def _statute( profile : Profile, assumptions : Assumptions ):
    """Compose the engine's statute: the jurisdiction (a Profile fact) with the tax projection (an
    Assumptions forward-view). Kept apart in the input aggregates, joined only here."""
    if assumptions.tax_projection is None:
        raise ValueError( 'Assumptions must carry a tax projection (from the default library).' )
    return StatuteProfile(
        jurisdiction_type = profile.jurisdiction_type,
        tax_projection    = assumptions.tax_projection,
        state_income_tax  = state_tax_policy( profile.us_state, profile.state_income_tax_rate ) )
