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
from dataclasses import dataclass
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
    RetirementContribution, ScheduledExternalDisbursement, Subject, SubsidizedHealthCoverage,
    WindowedAmount )

from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.law import StatuteProfile

from ucfp.parameter_sets.enums import PropertyContext, Realization

from ucfp.inputs.builtin_assumptions import BUILTIN_ASSUMPTIONS
from ucfp.inputs.expenses import OWNED_PROPERTY_CONTEXT
from ucfp.inputs.profile.enums import DebtKind, HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile, RENTED_HOME_HANDLE
from ucfp.inputs.plans.enums import CreditCardPlanMode
from ucfp.inputs.plans.schemas import (
    CreditCardPlan, LoanRepayment, Plans, RetirementTiming, VehiclePlan )
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.compatibility import assert_compatible

from ucfp.inputs.events import event_contributions


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
    expense_streams, expense_items = _property_expenses(
        profile, plans, assets_by_handle, events.property_sales )
    flow_streams, flow_items = _income_flows( profile, subjects_by_handle )
    card_items, card_events = _credit_card_expenses( profile, plans, frame.start_date )
    return ForecastParameters(
        start_date       = frame.start_date,
        end_date         = frame.end_date,
        filing_status    = profile.filing_status,
        statute          = statute,
        granularity      = frame.granularity,
        subjects         = subjects,
        assets           = _assets( profile ),
        economic_outlook = _economic_outlook( assumptions ),
        income_streams   = _entitlement_income(
            profile, plans, subjects_by_handle, government_pension ) + flow_streams,
        income_items     = flow_items + events.income_items,
        expense_items    = (
            _committed_obligations( profile ) + recurring_items + expense_items
            + events.expense_items + card_items + _vehicle_expenses( plans ) ),
        expense_streams  = recurring_streams + expense_streams,
        loans            = _loans( profile, plans ),
        contributions    = _contributions( plans ),
        events           = events.scheduled_events + card_events,
        cash_account     = _cash_account( plans ),
        health_coverage  = _health_coverage( plans ),
        subject_removals = events.subject_removals,
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
    becomes a loan once the plan supplies its terms."""
    repayments = { repayment.debt_handle : repayment for repayment in plans.loan_repayments }
    extra      = { prepayment.loan_handle : prepayment.annual_amount
                   for prepayment in plans.prepayments }
    assets     = { asset.handle : asset for asset in profile.assets }
    loans = []
    for debt in profile.debts:
        repayment = repayments.get( debt.handle )
        if not debt.kind.is_amortizing or repayment is None:
            continue
        interest_class = _debt_interest_class( debt, assets.get( debt.secured_asset ) )
        loans.append(
            _loan( debt, repayment, interest_class, extra.get( debt.handle, Decimal( '0' ) ) ) )
    return loans


def _loan( debt : Debt, repayment : LoanRepayment, interest_class : ExpenseTaxClass,
           extra_principal : Decimal ) -> LoanParameters:
    """The engine view of an amortizing debt: its current balance is the opening balance, repaid at
    the plan's rate over its remaining term (the engine projects forward from there). A Plans
    prepayment becomes the engine's annual extra principal."""
    return LoanParameters(
        name = debt.name, opening_balance = debt.balance, interest_rate = repayment.interest_rate,
        term = repayment.remaining_term, interest_class = interest_class,
        annual_extra_principal = extra_principal, handle = debt.handle )


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
_AUTO_LOAN_TERM_MONTHS = BUILTIN_ASSUMPTIONS.auto_loan_term_years * 12


def _vehicle_expenses( plans : Plans ) -> list[ ExpenseItem ]:
    """The household's car costs, smoothed: a lump every recurrence (the full price unfinanced, or the
    down payment financed) plus, when financed, a constant stream of the financed lifetime cost spread
    over the recurrence period. Both scale by the number of cars and begin at the plan's start date."""
    plan = plans.vehicle_plan
    if plan is None or not plan.num_cars or not plan.purchase_price or not plan.recurrence_years:
        return list()                                  # no cars, or no purchase pattern set
    cars   = Decimal( plan.num_cars )
    window = DateWindow( start = plan.start_date )
    lump, financed_lifetime = _vehicle_costs( plan )
    items = list()
    if lump > 0:
        items.append( ExpenseItem(
            name = 'Car purchase', expense_tax_class = ExpenseTaxClass.LIVING,
            amounts = Schedule.constant( WindowedAmount( lump * cars ) ),
            cadence = Recurrence( Duration( plan.recurrence_years, TimeUnit.YEAR ) ),
            window = window ) )
    if financed_lifetime > 0:
        monthly = financed_lifetime * cars / ( plan.recurrence_years * 12 )
        items.append( ExpenseItem(
            name = 'Car payments', expense_tax_class = ExpenseTaxClass.LIVING,
            amounts = Schedule.constant( WindowedAmount( monthly ) ),
            cadence = Recurrence( Duration( 1, TimeUnit.MONTH ) ), window = window ) )
    return items


def _vehicle_costs( plan : VehiclePlan ) -> tuple[ Decimal, Decimal ]:
    """The (per-car lump, per-car financed lifetime cost) of the plan. Unfinanced: the lump is the
    full price, nothing financed. Financed: the lump is the down payment and the financed lifetime
    cost is the total of the loan's payments (principal plus interest). The user gives the down
    payment or the monthly payment; the other is derived at the assumed rate and term."""
    rate  = _AUTO_LOAN_APR.fraction / 12
    term  = _AUTO_LOAN_TERM_MONTHS
    price = plan.purchase_price
    if plan.down_payment is not None:
        financed = max( price - plan.down_payment, Decimal( '0' ) )
        payment  = level_payment( financed, rate, term ) if financed > 0 else Decimal( '0' )
        return plan.down_payment, payment * term
    if plan.monthly_payment is not None:
        financed = present_value( plan.monthly_payment, rate, term )
        return max( price - financed, Decimal( '0' ) ), plan.monthly_payment * term
    return price, Decimal( '0' )   # unfinanced: the whole price is the lump


# --- Profile: flows (income entitlements, committed obligations) -----------

def _income_flows(
        profile : Profile, subjects_by_handle : dict[ str, Subject ] ) -> tuple[ list, list ]:
    """The profile's income flows as (streams, items): a flow with no interval is a smoothed stream,
    one with an interval an item placed at that cadence (rent is monthly). The flow's `schedule`
    carries its own window, and its `property_handle` is carried to the engine as the income's
    `source_handle` (rental income keeps its property link)."""
    streams, items = list(), list()
    for flow in profile.income_flows:
        subject = ( subjects_by_handle[ flow.subject_handle ]
                    if flow.subject_handle is not None else None )   # None -> household income
        amounts = Schedule( tuple( flow.schedule ) )
        if flow.interval is None:
            streams.append( IncomeStream(
                subject = subject, income_tax_class = flow.income_tax_class,
                amounts = amounts, source_handle = flow.property_handle ) )
        else:
            items.append( IncomeItem(
                subject = subject, income_tax_class = flow.income_tax_class,
                amounts = amounts, cadence = Recurrence( flow.interval ),
                source_handle = flow.property_handle ) )
    return streams, items


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
            income_tax_class = IncomeTaxClass.ORDINARY,
            amounts = Schedule.constant( WindowedAmount( pension.base_annual_amount ) ),
            window = DateWindow( start = _pension_start( timing.get( pension.subject_handle ) ) ) ) )
    for entitlement in profile.government_pension:
        subject = subjects_by_handle[ entitlement.subject_handle ]
        claiming = _claiming_date(
            timing.get( entitlement.subject_handle ), entitlement.subject_handle )
        streams.append( IncomeStream(
            subject = subject,
            income_tax_class = government_pension.income_tax_class(),
            amounts = Schedule.constant( WindowedAmount( government_pension.realized_annual_benefit(
                entitlement.monthly_at_normal_age, subject.birthdate, claiming ) ) ),
            window = DateWindow( start = claiming ) ) )
    return streams


def _pension_start( timing : Optional[ RetirementTiming ] ) -> Optional[ date ]:
    return timing.pension_start if timing is not None else None


def _claiming_date( timing : Optional[ RetirementTiming ], subject_handle : str ) -> date:
    if timing is None or timing.government_pension_claiming_date is None:
        raise ValueError(
            f'The government pension for "{subject_handle}" needs a claiming date in the plans '
            'timing.' )
    return timing.government_pension_claiming_date


def _committed_obligations( profile : Profile ) -> list[ ExpenseItem ]:
    """The profile's committed non-loan outflows -- placed at their cadence."""
    return [ ExpenseItem(
        name = obligation.name, expense_tax_class = obligation.expense_tax_class,
        amounts = Schedule.constant( WindowedAmount( obligation.amount ) ),
        cadence = Recurrence( obligation.cadence ),
        window = DateWindow( end = obligation.through ), handle = obligation.handle )
        for obligation in profile.obligations ]


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
                name = expense.name, expense_tax_class = expense.expense_tax_class,
                amounts = _annualized( amounts, expense.interval ) ) )
        else:
            items.append( ExpenseItem(
                name = expense.name, expense_tax_class = expense.expense_tax_class,
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


def _property_expenses( profile : Profile, plans : Plans, assets : dict,
                        sale_dates : dict ) -> tuple[ list, list ]:
    """The Plans' property operating expenses as (streams, items): each expense applied to every property
    its `applies_to` reaches, at that property's override or the shared default (skipped when both are
    blank or zero), with the tax class derived from the property and the amount clipped to the property's
    ownership window -- its sale date, when it is sold. A SMOOTH expense enters as an annualized stream; a
    DISCRETE one as an item placed at its cadence."""
    streams, items = list(), list()
    for expense in plans.property_expenses:
        for handle, context, asset in _property_contexts( profile ):
            if context not in expense.applies_to:
                continue
            amount = expense.overrides.get( handle, expense.default_amount )
            if not amount:
                continue
            tax_class = _property_expense_tax_class( expense, asset )
            amounts   = _property_schedule( amount, sale_dates.get( handle ) )
            if expense.realization is Realization.SMOOTH:
                streams.append( ExpenseStream(
                    name = expense.name, expense_tax_class = tax_class,
                    amounts = _annualized( amounts, expense.interval ) ) )
            else:
                items.append( ExpenseItem(
                    name = expense.name, expense_tax_class = tax_class,
                    amounts = amounts, cadence = Recurrence( expense.interval ) ) )
    return streams, items


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

def _contributions( plans : Plans ) -> list[ RetirementContribution ]:
    return [ RetirementContribution(
        account = contribution.account_handle, amount = contribution.annual_amount,
        source = contribution.source, window = DateWindow( end = contribution.through ) )
        for contribution in plans.contributions ]


def _cash_account( plans : Plans ) -> CashAccountParameters:
    drawdown = plans.drawdown
    if drawdown is None:
        return CashAccountParameters()
    sweep = AssetAllocation( tuple( drawdown.sweep_allocation ) ) if drawdown.sweep_allocation else None
    return CashAccountParameters(
        cash_floor = drawdown.cash_floor, cash_ceiling = drawdown.cash_ceiling,
        draw_order = list( drawdown.draw_order ), sweep_allocation = sweep )


def _health_coverage( plans : Plans ) -> Optional[ SubsidizedHealthCoverage ]:
    coverage = plans.health_coverage
    if coverage is None:
        return None
    return SubsidizedHealthCoverage(
        window = DateWindow( start = coverage.start, end = coverage.through ),
        household_size = coverage.household_size, reference_premium = coverage.reference_premium )


# --- Assumptions: external factors (reuse engine types; no zero-fill) ---------

def _economic_outlook( assumptions : Assumptions ) -> EconomicOutlook:
    """The assumptions' own economic-factors copy as the engine's outlook -- a constant outlook for
    now. The copy is seeded from a library preset at input time, so there is no library load here."""
    if assumptions.economics is None:
        raise ValueError( 'Assumptions must carry economic factors (seed them from a preset).' )
    return EconomicOutlook.constant( assumptions.economics )


def _statute( profile : Profile, assumptions : Assumptions ):
    """Compose the engine's statute: the jurisdiction (a Profile fact) with the tax projection (an
    Assumptions forward-view). Kept apart in the input aggregates, joined only here."""
    if assumptions.tax_projection is None:
        raise ValueError( 'Assumptions must carry a tax projection (from the default library).' )
    return StatuteProfile(
        jurisdiction_type = profile.jurisdiction_type,
        tax_projection = assumptions.tax_projection )
