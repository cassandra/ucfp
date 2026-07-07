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
from common.rate import Rate
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.environment.constants import AppConst
from ucfp.forecast.economic_outlook import EconomicOutlook
from ucfp.forecast.parameters import (
    AssetAllocation, AssetParameters, CashAccountParameters, ExpenseItem, ExpenseStream,
    ForecastParameters, IncomeItem, IncomeStream, LoanParameters, PropertyAttributes,
    RetirementContribution, ScheduledExternalDisbursement, Subject, SubsidizedHealthCoverage,
    WindowedAmount )

from ucfp.parameter_sets import repository as parameter_sets
from ucfp.parameter_sets.enums import ParameterSetKind
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.law import StatuteProfile

from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile
from ucfp.inputs.plans.enums import CreditCardPlanMode
from ucfp.inputs.plans.schemas import (
    AutoPlan, CreditCardPlan, LoanRepayment, RetirementTiming, Plans )
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
    lifestyle_streams, lifestyle_items = _lifestyle_expenses( plans )
    expense_streams, expense_items = _plans_expenses( plans )
    flow_streams, flow_items = _income_flows( profile, subjects_by_handle )
    events = event_contributions( profile, plans, subjects_by_handle )
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
            _committed_obligations( profile ) + lifestyle_items + expense_items
            + events.expense_items + card_items + _auto_expenses( plans ) ),
        expense_streams  = lifestyle_streams + expense_streams,
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

# The nominal APR the paydown calculator and this resolver assume, shared via AppConst so the
# client-side estimate and the server-side materialization cannot drift.
_CREDIT_CARD_APR = Rate.percent( Decimal( AppConst.CREDIT_CARD_APR_PERCENT ) )


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


# --- Plans: auto (car ownership) -----------------------------------------

_AUTO_LOAN_APR         = Rate.percent( Decimal( AppConst.AUTO_LOAN_APR_PERCENT ) )
_AUTO_LOAN_TERM_MONTHS = AppConst.AUTO_LOAN_TERM_YEARS * 12


def _auto_expenses( plans : Plans ) -> list[ ExpenseItem ]:
    """The household's car costs, smoothed: a lump every recurrence (the full price unfinanced, or the
    down payment financed) plus, when financed, a constant stream of the financed lifetime cost spread
    over the recurrence period. Both scale by the number of cars and begin at the plan's start date."""
    plan = plans.auto_plan
    if plan is None or plan.num_cars <= 0 or plan.purchase_price <= 0 or plan.recurrence_years <= 0:
        return list()
    cars   = Decimal( plan.num_cars )
    window = DateWindow( start = plan.start_date )
    lump, financed_lifetime = _auto_costs( plan )
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


def _auto_costs( plan : AutoPlan ) -> tuple[ Decimal, Decimal ]:
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


def _lifestyle_expenses( plans : Plans ) -> tuple[ list, list ]:
    """The Plans' lifestyle as (streams, items): load its chosen cost table from the
    parameter-set library and step each expense by the level in effect across the timeline --
    a stream (no `interval`) smoothed, an item (an `interval`) placed at its cadence."""
    lifestyle = plans.lifestyle
    if lifestyle is None:
        return list(), list()
    table = parameter_sets.load( ParameterSetKind.LIFESTYLE_COSTS, lifestyle.scope.label )
    if not table.expenses:
        return list(), list()
    segments = _lifestyle_segments( lifestyle )
    streams, items = list(), list()
    for expense in table.expenses:
        amounts = _level_schedule( expense.amounts, segments )
        if expense.interval is None:
            streams.append( ExpenseStream(
                name = expense.name, expense_tax_class = expense.expense_tax_class,
                amounts = amounts ) )
        else:
            items.append( ExpenseItem(
                name = expense.name, expense_tax_class = expense.expense_tax_class,
                amounts = amounts, cadence = Recurrence( expense.interval ) ) )
    return streams, items


def _lifestyle_segments( lifestyle ) -> list:
    if not lifestyle.segments:
        raise ValueError(
            'A lifestyle plan needs at least one schedule segment to apply the cost table.' )
    return sorted( lifestyle.segments, key = lambda segment: segment.start )


def _level_schedule( amounts, segments : list ) -> Schedule:
    """A `Schedule[WindowedAmount]` stepping `amounts` by the level in effect across each
    schedule span. The first span runs from the start of the horizon, the last to its end."""
    windowed = list()
    for index, segment in enumerate( segments ):
        start = None if index == 0 else segment.start
        end = ( segments[ index + 1 ].start - timedelta( days = 1 )
                if index + 1 < len( segments ) else None )
        windowed.append( WindowedAmount(
            amounts.for_level( segment.level ), DateWindow( start = start, end = end ) ) )
    return Schedule( tuple( windowed ) )


def _plans_expenses( plans : Plans ) -> tuple[ list, list ]:
    """The Plans' planned expenses as (streams, items): a flow with no interval is a smoothed
    stream, one with an interval an item placed at that cadence. Each is a flat amount for now;
    value-steps over time come later. The successor to `_lifestyle_expenses`."""
    streams, items = list(), list()
    for expense in plans.expenses:
        amounts = Schedule( tuple( expense.schedule ) )
        if expense.interval is None:
            streams.append( ExpenseStream(
                name = expense.name, expense_tax_class = expense.expense_tax_class,
                amounts = amounts ) )
        else:
            items.append( ExpenseItem(
                name = expense.name, expense_tax_class = expense.expense_tax_class,
                amounts = amounts, cadence = Recurrence( expense.interval ) ) )
    return streams, items


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
