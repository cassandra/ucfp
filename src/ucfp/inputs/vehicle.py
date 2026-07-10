"""§ Vehicle Expenses -- the car purchase/financing pane.

A future car is never modeled as a loan (an *existing* auto loan is -- that lives in Debts and the
Debt plan). This captures the ongoing pattern of buying cars: how many, how often, at what price,
and -- if financed -- either a down payment or a monthly payment. It is stored as a `VehiclePlan`
(intent), which materialization smooths into a lump every recurrence plus, when financed, a constant
financed-cost stream, so the forecast carries no start/stop. The recurring-costs start date is
pre-filled from an existing auto loan's end date (so the pattern begins where a current loan leaves
off) but is freely editable. The plan's per-car running costs are entered in a sibling pane.
"""
from dataclasses import replace
from datetime import date

from django import forms

from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.schemas import VehiclePlan
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.vehicle_expenses import plan_has_content, vehicle_plan_of
from ucfp.inputs.widgets import IsoDateInput


class VehiclePlanForm( forms.Form ):
    """The household's car purchase pattern as one auto-saving pane: number of cars, typical purchase
    price, how often they are replaced, when the pattern starts, and -- if financed -- either a down
    payment or a monthly payment. `num_cars` is the shared quantity the sibling running-costs pane also
    scales by. Non-blocking: the purchase pattern materializes only once cars, price, and recurrence are
    all set; financing is optional (its absence means cash). `apply` writes the purchase fields onto the
    vehicle plan while carrying over the running costs the other pane saved, leaving the rest of Plans
    intact."""

    num_cars         = forms.IntegerField( label = 'Number of cars', required = False, min_value = 1 )
    purchase_price   = forms.DecimalField(
        label = 'Typical price per car', required = False, min_value = 0 )
    recurrence_years = forms.IntegerField(
        label = 'Replace a car every (years)', required = False, min_value = 1 )
    start_date       = forms.DateField(
        label = 'Recurring car costs start', required = False, widget = IsoDateInput() )
    down_payment     = forms.DecimalField(
        label = 'Down payment (if financed)', required = False, min_value = 0 )
    monthly_payment  = forms.DecimalField(
        label = 'Monthly payment (if financed)', required = False, min_value = 0 )

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__(
            data, initial = self._initial( profile, plans ) if profile is not None else None )
        self.fields[ 'num_cars' ].widget.attrs[ 'class' ] = AppConst.VEHICLE_NUM_CARS_CLASS

    @classmethod
    def _initial( cls, profile, plans ) -> dict:
        plan = plans.vehicle_plan if plans is not None else None
        if plan is not None:
            return {
                'num_cars'         : plan.num_cars,
                'purchase_price'   : plan.purchase_price,
                'recurrence_years' : plan.recurrence_years,
                # A plan can exist from a running-costs edit before the purchase pane is opened, so fall
                # back to the auto-loan-end prefill when its start date has not been set yet.
                'start_date'       : plan.start_date or cls._auto_loan_end( profile, plans ),
                'down_payment'     : plan.down_payment,
                'monthly_payment'  : plan.monthly_payment,
            }
        start = cls._auto_loan_end( profile, plans )
        return { 'start_date': start } if start is not None else dict()

    @staticmethod
    def _auto_loan_end( profile, plans ):
        """The end date of an existing auto loan -- today plus its remaining term -- to pre-fill the
        recurring-costs start, so the pattern begins where a current loan leaves off. None when there
        is no amortizing auto loan with repayment terms set."""
        if plans is None:
            return None
        loan = next( ( debt for debt in profile.debts if debt.kind is DebtKind.AUTO ), None )
        if loan is None:
            return None
        repayment = next(
            ( r for r in plans.loan_repayments if r.debt_handle == loan.handle ), None )
        if repayment is None:
            return None
        years = repayment.remaining_term.months() // 12
        today = date.today()
        try:
            return today.replace( year = today.year + years )
        except ValueError:                     # today is Feb 29 and the target year is not a leap year
            return today.replace( year = today.year + years, day = 28 )

    def apply( self, profile, plans ):
        return profile, replace( plans, vehicle_plan = self._plan( plans ) )

    def _plan( self, plans ):
        # Aspect-preserving and non-blocking: store whatever purchase fields are set (materialization
        # uses only the complete purchase pattern) and carry over any running costs the sibling pane
        # saved. Financing (down or monthly) is optional -- its absence means cash. A wholly empty plan
        # -- no purchase field and no running cost with an amount -- persists as None (`plan_has_content`,
        # shared with the running-costs pane so the two agree on "empty").
        cleaned  = self.cleaned_data
        existing = vehicle_plan_of( plans )
        plan = VehiclePlan(
            num_cars = cleaned.get( 'num_cars' ),
            purchase_price = cleaned.get( 'purchase_price' ),
            recurrence_years = cleaned.get( 'recurrence_years' ),
            start_date = cleaned.get( 'start_date' ),
            monthly_payment = cleaned.get( 'monthly_payment' ),
            down_payment = cleaned.get( 'down_payment' ),
            running_costs = existing.running_costs if existing is not None else list() )
        return plan if plan_has_content( plan ) else None
