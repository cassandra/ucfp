"""Materialize a Profile + Scenario + run frame into the engine's `ForecastParameters`.

The seam between the user-facing planning model and the Forecast engine: it composes the
facts (`Profile`), the assumptions (`Scenario`), and the run frame into the single
`ForecastParameters` the engine consumes. It lives in `planning` -- above profile, scenario,
and the engine -- so neither input app depends on the other and the engine depends on neither.

Social Security composes the entitlement fact (PIA) with the claiming-age knob through the
jurisdiction-neutral `tax.government_pension` layer (the statutory schedule lives behind it,
in the jurisdiction layer, not here). Pension is materialized as its base benefit from the
chosen start date; plan-specific actuarial reduction is deferred (it is plan data, not a
general rule). Lifestyle expenses materialize per the engine's 2x2 -- smoothed categories to
expense streams, cadenced ones to placed items -- each stepping as the scheduled level changes.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from common.amortization import remaining_balance
from common.date_window import DateWindow
from common.recurrence import Duration, Recurrence, TimeUnit
from common.schedule import Schedule

from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook
from ucfp.forecast.parameters import (
    AssetAllocation, AssetParameters, CashAccountParameters, ExpenseItem, ExpenseStream,
    ForecastParameters, IncomeItem, IncomeStream, LoanParameters, PropertyAttributes,
    RetirementContribution, Subject, SubsidizedHealthCoverage, WindowedAmount )

from ucfp.parameter_sets import repository as parameter_sets
from ucfp.parameter_sets.enums import ParameterSetKind
from ucfp.tax.government_pension import GovernmentPension

from ucfp.profile.schemas import AssetProfile, LoanProfile, Profile
from ucfp.scenario.schemas import RetirementTiming, Scenario

from .events import event_contributions


@dataclass( frozen = True )
class ForecastFrame:
    """The run configuration the engine needs that is neither a fact nor an assumption -- the
    horizon and granularity. Provided per run (often implied by the planning perspective), not
    stored in a Profile or Scenario."""

    start_date  : date
    end_date    : date
    granularity : Duration = Duration( 1, TimeUnit.YEAR )


def materialize(
        profile : Profile, scenario : Scenario, frame : ForecastFrame ) -> ForecastParameters:
    if profile.filing_status is None:
        raise ValueError( 'A profile must set its filing status before a forecast can run.' )
    tax_forecast = _tax_forecast( scenario )
    subjects = _subjects( profile )
    subjects_by_handle = { str( subject.handle ): subject
                           for subject in subjects if subject.handle is not None }
    government_pension = GovernmentPension( tax_forecast.tax_law_type )
    lifestyle_streams, lifestyle_items = _lifestyle_expenses( scenario )
    expense_streams, expense_items = _scenario_expenses( scenario )
    events = event_contributions( profile, scenario, subjects_by_handle )
    return ForecastParameters(
        start_date       = frame.start_date,
        end_date         = frame.end_date,
        filing_status    = profile.filing_status,
        tax_forecast     = tax_forecast,
        granularity      = frame.granularity,
        subjects         = subjects,
        assets           = _assets( profile ),
        economic_outlook = _economic_outlook( scenario ),
        income_streams   = _income_streams(
            profile, scenario, subjects_by_handle, government_pension ),
        income_items     = _rental_income( profile, subjects_by_handle ) + events.income_items,
        expense_items    = (
            _committed_obligations( profile ) + lifestyle_items + expense_items
            + events.expense_items ),
        expense_streams  = lifestyle_streams + expense_streams,
        loans            = _loans( profile, scenario, frame.start_date ),
        contributions    = _contributions( scenario ),
        events           = events.scheduled_events,
        cash_account     = _cash_account( scenario ),
        health_coverage  = _health_coverage( scenario ),
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


def _loans( profile : Profile, scenario : Scenario, as_of : date ) -> list[ LoanParameters ]:
    extra = { prepayment.loan_handle: prepayment.annual_amount
              for prepayment in scenario.prepayments }
    return [ _loan( loan, as_of, extra.get( loan.handle, Decimal( '0' ) ) )
             for loan in profile.loans ]


def _loan( loan : LoanProfile, as_of : date, extra_principal : Decimal ) -> LoanParameters:
    """The engine view of a loan as of the forecast start: amortize the original loan from its
    origination to the balance still owed (unless `current_balance` overrides it) and the
    remaining term, since the engine projects forward from an opening balance over a term. A
    scenario prepayment becomes the engine's annual extra principal."""
    periods = loan.original_term.months()
    elapsed = min( _elapsed_months( loan.origination_date, as_of ), periods )
    opening = loan.current_balance if loan.current_balance is not None else remaining_balance(
        loan.original_amount, loan.interest_rate.fraction / 12, periods, elapsed )
    return LoanParameters(
        name = loan.name, opening_balance = opening, interest_rate = loan.interest_rate,
        term = Duration( max( periods - elapsed, 1 ), TimeUnit.MONTH ),
        interest_class = loan.interest_class or ExpenseTaxClass.NON_DEDUCTIBLE_INTEREST,
        annual_extra_principal = extra_principal, handle = loan.handle )


def _elapsed_months( origination : date, as_of : date ) -> int:
    """Whole months from `origination` to `as_of`, floored at zero (a not-yet-originated loan has
    not begun amortizing)."""
    months = ( as_of.year - origination.year ) * 12 + ( as_of.month - origination.month )
    return max( months, 0 )


# --- Profile: flows (income entitlements, committed obligations) -----------

def _income_streams(
        profile : Profile, scenario : Scenario, subjects_by_handle : dict[ str, Subject ],
        government_pension : GovernmentPension ) -> list[ IncomeStream ]:
    timing = { entry.subject_handle: entry for entry in scenario.timing }
    streams = list()
    for salary in profile.salaries:
        streams.append( IncomeStream(
            subject = subjects_by_handle[ salary.subject_handle ],
            income_tax_class = IncomeTaxClass.WAGES,
            amounts = Schedule.constant( WindowedAmount( salary.annual_amount ) ),
            window = DateWindow( end = _salary_end( timing.get( salary.subject_handle ) ) ) ) )
    for pension in profile.pensions:
        streams.append( IncomeStream(
            subject = subjects_by_handle[ pension.subject_handle ],
            income_tax_class = IncomeTaxClass.ORDINARY,
            amounts = Schedule.constant( WindowedAmount( pension.base_annual_amount ) ),
            window = DateWindow( start = _pension_start( timing.get( pension.subject_handle ) ) ) ) )
    for entitlement in profile.government_pension:
        subject = subjects_by_handle[ entitlement.subject_handle ]
        claiming_age = _claiming_age(
            timing.get( entitlement.subject_handle ), entitlement.subject_handle )
        streams.append( IncomeStream(
            subject = subject,
            income_tax_class = government_pension.income_tax_class(),
            amounts = Schedule.constant( WindowedAmount( government_pension.realized_annual_benefit(
                entitlement.monthly_at_normal_age, subject.birthdate, claiming_age ) ) ),
            window = DateWindow( start = _claiming_date( subject.birthdate, claiming_age ) ) ) )
    return streams


def _salary_end( timing : Optional[ RetirementTiming ] ) -> Optional[ date ]:
    """A salary runs until retirement: the explicit salary-stop date, else the retirement
    date, else open-ended."""
    if timing is None:
        return None
    return timing.salary_stop or timing.retirement_date


def _pension_start( timing : Optional[ RetirementTiming ] ) -> Optional[ date ]:
    return timing.pension_start if timing is not None else None


def _claiming_age( timing : Optional[ RetirementTiming ], subject_handle : str ) -> int:
    if timing is None or timing.government_pension_claiming_age is None:
        raise ValueError(
            f'The government pension for "{subject_handle}" needs a claiming age in the '
            'scenario timing.' )
    return timing.government_pension_claiming_age


def _claiming_date( birthdate : date, claiming_age : int ) -> date:
    """The date the subject reaches `claiming_age` (Feb 29 clamped to Feb 28)."""
    year = birthdate.year + claiming_age
    try:
        return birthdate.replace( year = year )
    except ValueError:
        return birthdate.replace( year = year, day = 28 )


def _rental_income(
        profile : Profile, subjects_by_handle : dict[ str, Subject ] ) -> list[ IncomeItem ]:
    """Each rental's gross rent as a monthly recurring `GROSS_RENTAL` income item, reported by the
    property's owner (the primary subject if the property names none -- tax-neutral when filing
    jointly). A bounded existence window comes later, when a sale ends it."""
    assets = { asset.handle: asset for asset in profile.assets }
    items  = list()
    for rental in profile.rental_incomes:
        property_asset = assets.get( rental.property_handle )
        owner   = property_asset.owner_handle if property_asset is not None else None
        subject = subjects_by_handle.get( owner ) or subjects_by_handle[ profile.subjects[ 0 ].handle ]
        items.append( IncomeItem(
            subject = subject, income_tax_class = IncomeTaxClass.GROSS_RENTAL,
            amounts = Schedule.constant( WindowedAmount( rental.monthly_amount ) ),
            cadence = Recurrence( Duration( 1, TimeUnit.MONTH ) ) ) )
    return items


def _committed_obligations( profile : Profile ) -> list[ ExpenseItem ]:
    """The profile's committed non-loan outflows -- placed at their cadence."""
    return [ ExpenseItem(
        name = obligation.name, expense_tax_class = obligation.expense_tax_class,
        amounts = Schedule.constant( WindowedAmount( obligation.amount ) ),
        cadence = Recurrence( obligation.cadence ),
        window = DateWindow( end = obligation.through ), handle = obligation.handle )
        for obligation in profile.obligations ]


def _lifestyle_expenses( scenario : Scenario ) -> tuple[ list, list ]:
    """The scenario's lifestyle as (streams, items): load its chosen cost table from the
    parameter-set library and step each expense by the level in effect across the timeline --
    a stream (no `interval`) smoothed, an item (an `interval`) placed at its cadence."""
    lifestyle = scenario.lifestyle
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


def _scenario_expenses( scenario : Scenario ) -> tuple[ list, list ]:
    """The scenario's planned expenses as (streams, items): a flow with no interval is a smoothed
    stream, one with an interval an item placed at that cadence. Each is a flat amount for now;
    value-steps over time come later. The successor to `_lifestyle_expenses`."""
    streams, items = list(), list()
    for expense in scenario.expenses:
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


# --- Scenario: knobs -------------------------------------------------------

def _contributions( scenario : Scenario ) -> list[ RetirementContribution ]:
    return [ RetirementContribution(
        account = contribution.account_handle, amount = contribution.annual_amount,
        source = contribution.source, window = DateWindow( end = contribution.through ) )
        for contribution in scenario.contributions ]


def _cash_account( scenario : Scenario ) -> CashAccountParameters:
    drawdown = scenario.drawdown
    if drawdown is None:
        return CashAccountParameters()
    sweep = AssetAllocation( tuple( drawdown.sweep_allocation ) ) if drawdown.sweep_allocation else None
    return CashAccountParameters(
        cash_floor = drawdown.cash_floor, cash_ceiling = drawdown.cash_ceiling,
        draw_order = list( drawdown.draw_order ), sweep_allocation = sweep )


def _health_coverage( scenario : Scenario ) -> Optional[ SubsidizedHealthCoverage ]:
    coverage = scenario.health_coverage
    if coverage is None:
        return None
    return SubsidizedHealthCoverage(
        window = DateWindow( start = coverage.start, end = coverage.through ),
        household_size = coverage.household_size, reference_premium = coverage.reference_premium )


# --- Scenario: external factors (reuse engine types; no zero-fill) ---------

def _economic_outlook( scenario : Scenario ) -> EconomicOutlook:
    """The scenario's own economic-factors copy as the engine's outlook -- a constant outlook for
    now. The copy is seeded from a library preset at input time, so there is no library load here."""
    if scenario.economics is None:
        raise ValueError( 'A scenario must carry economic factors (seed them from a preset).' )
    return EconomicOutlook.constant( scenario.economics )


def _tax_forecast( scenario : Scenario ):
    if scenario.tax_forecast is None:
        raise ValueError( 'A scenario must carry a tax forecast (from the default library).' )
    return scenario.tax_forecast
