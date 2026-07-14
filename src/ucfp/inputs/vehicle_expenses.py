"""The per-car vehicle running costs of the Vehicle Expenses step.

The household's car running costs (fuel, insurance, maintenance, repair) are entered once *per car* and
scaled by the vehicle plan's shared `num_cars`. They are seeded from the curated catalog's `VEHICLE`
rows and stored on the `VehiclePlan` (alongside the purchase/financing pattern), not with the general
recurring expenses -- a shared-quantity shape distinct from the independent, per-age recurring costs.
This module seeds those costs from the catalog, preserving amounts and cadences already set.
"""
from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP

from django import forms

from ucfp.environment.constants import AppConst
from ucfp.parameter_sets.enums import ExpenseClass
from ucfp.inputs.plans.schemas import VehiclePlan, VehicleRunningCost
from ucfp.inputs.cadence import add_cadence_fields, cadence_cells, read_cadence
from ucfp.inputs.expenses import kept_interval, ordered_catalog


def vehicle_plan_of( plans ):
    """The Plans aggregate's vehicle plan, or None when there is no aggregate or no plan yet -- the
    single guard both vehicle panes read the plan through."""
    return plans.vehicle_plan if plans is not None and plans.vehicle_plan is not None else None


def plan_has_content( plan ) -> bool:
    """Whether a vehicle plan carries anything worth persisting -- any vehicle, or a running cost with an
    amount. An all-blank plan (no vehicles, every running-cost amount cleared) is empty, so both panes
    collapse it back to None rather than leaving a spurious plan that reads as "started"."""
    if plan is None:
        return False
    return ( bool( plan.vehicles )
             or any( cost.amount is not None for cost in plan.running_costs ) )


def merged_vehicle_costs( plans ) -> list:
    """The catalog's `VEHICLE` rows as `VehicleRunningCost`s -- each existing per-car amount (and any
    chosen cadence) preserved, missing ones seeded at the catalog default. The tax class and realization
    are re-derived from the catalog each merge (not user edits)."""
    plan     = vehicle_plan_of( plans )
    existing = { cost.handle: cost for cost in plan.running_costs } if plan is not None else dict()
    merged = list()
    for catalog_expense in ordered_catalog():
        if catalog_expense.expense_class is not ExpenseClass.VEHICLE:
            continue
        prior = existing.get( catalog_expense.handle )
        merged.append( VehicleRunningCost(
            name = catalog_expense.name, handle = catalog_expense.handle,
            expense_tax_class = catalog_expense.expense_tax_class,
            interval = kept_interval( prior, catalog_expense ),
            realization = catalog_expense.realization,
            cadence_domain = catalog_expense.cadence_domain,
            amount = prior.amount if prior is not None else catalog_expense.default_amount ) )
    return merged


class VehicleExpensesForm( forms.Form ):
    """The per-car running-costs table of the Vehicle Expenses step: one row per running cost, each a
    per-car amount at its own cadence, with a read-only total (the per-car amount times the plan's car
    count, at the same cadence) shown alongside. Auto-saves each edit onto the vehicle plan's
    `running_costs`; the row set is fixed (the catalog's vehicle costs), so it never restructures.
    `apply` writes the running costs onto the plan, creating one if the household has not begun a
    vehicle plan yet. The car count the totals scale by lives on the sibling purchase pane."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._costs    = merged_vehicle_costs( plans )
        # INTERIM (#84 Phase 1): the fleet count is now time-varying (per-vehicle windows), so the
        # single-count scaled-total preview no longer applies. Phase 2 reworks this pane; until then the
        # total column simply shows a dash.
        self._num_cars = None
        for ci, cost in enumerate( self._costs ):
            amount = forms.DecimalField( required = False, min_value = 0 )
            amount.initial = cost.amount
            amount.widget.attrs[ 'class' ]      = AppConst.VEHICLE_PERCAR_CLASS
            amount.widget.attrs[ 'aria-label' ] = f'{cost.name} — per car'
            self.fields[ self._amount_key( ci ) ] = amount
            add_cadence_fields( self, self._cad_prefix( ci ), cost.interval, cost.cadence_domain )

    @staticmethod
    def _amount_key( ci : int ) -> str:
        return f'amount_{ci}'

    @staticmethod
    def _cad_prefix( ci : int ) -> str:
        return f'cad_{ci}'

    @property
    def num_cars( self ):
        """The plan's car count the totals scale by (None until set) -- shown in the table caption."""
        return self._num_cars

    @property
    def rows( self ) -> list:
        """One row per running cost: its name, the per-car amount field, its cadence control, and the
        read-only scaled total (per-car amount times the car count, whole dollars; None until both are
        known -- the cadence column carries the period the total is expressed at)."""
        return [ {
            'name'    : cost.name,
            'amount'  : self[ self._amount_key( ci ) ],
            'cadence' : cadence_cells( self, self._cad_prefix( ci ), cost.interval, cost.cadence_domain ),
            'total'   : self._total( cost ) }
            for ci, cost in enumerate( self._costs ) ]

    def _total( self, cost ):
        """The scaled per-period total -- the per-car amount times the plan's car count -- as whole
        dollars, or None when the amount is blank or the car count is unset (nothing to total). Rounded
        half-up to agree with the client's `Math.round` preview (Decimal's default is half-even)."""
        if cost.amount is None or not self._num_cars:
            return None
        return ( cost.amount * self._num_cars ).quantize( Decimal( 1 ), rounding = ROUND_HALF_UP )

    def apply( self, profile, plans ):
        costs = [ self._edited( ci, cost ) for ci, cost in enumerate( self._costs ) ]
        plan  = replace( vehicle_plan_of( plans ) or VehiclePlan(), running_costs = costs )
        return profile, replace( plans, vehicle_plan = plan if plan_has_content( plan ) else None )

    def _edited( self, ci : int, cost ) -> VehicleRunningCost:
        """`cost` with its per-car amount and cadence re-read from this row's fields."""
        interval = read_cadence( self, self._cad_prefix( ci ), cost.interval, cost.cadence_domain )
        amount   = self.cleaned_data.get( self._amount_key( ci ) )
        return replace( cost, interval = interval, amount = amount )
