"""The per-car vehicle running costs of the Vehicle plan step.

The household's car running costs (fuel, insurance, maintenance, repair) are entered once *per car* and
applied to each owned vehicle over its window at materialization. They are seeded from the curated
catalog's `VEHICLE` rows and stored on the `VehiclePlan` (alongside its list of vehicles), not with the
general recurring expenses -- a shared-quantity shape distinct from the independent, per-age recurring
costs. This module seeds those costs from the catalog, preserving amounts and cadences already set.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField

from ucfp.parameter_sets.enums import ExpenseClass
from ucfp.inputs.plans.schemas import VehiclePlan, VehicleRunningCost
from ucfp.inputs.cadence import add_cadence_fields, cadence_cells, read_cadence
from ucfp.inputs.expenses import kept_interval, ordered_catalog


def vehicle_plan_of( plans ):
    """The Plans aggregate's vehicle plan, or None when there is no aggregate or no plan yet -- the
    single guard both vehicle panes read the plan through."""
    return plans.vehicle_plan if plans is not None and plans.vehicle_plan is not None else None


def plan_has_content( plan ) -> bool:
    """Whether a vehicle plan carries anything worth persisting -- any owned- or leased-vehicle
    disposition, any net-new vehicle, or a running cost with an amount. An all-blank plan (nothing set)
    is empty, so every pane collapses it back to None rather than leaving a spurious plan that reads as
    "started"."""
    if plan is None:
        return False
    return ( bool( plan.dispositions ) or bool( plan.leased_dispositions ) or bool( plan.vehicles )
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
    """The per-car running-costs table of the Vehicle plan step: one row per running cost, each a
    per-car amount at its own cadence. Auto-saves each edit onto the vehicle plan's `running_costs`; the
    row set is fixed (the catalog's vehicle costs), so it never restructures. `apply` writes the running
    costs onto the plan, creating one if the household has not begun a vehicle plan yet. The amount is a
    single per-car figure; materialization applies it to each owned vehicle over its window, so the total
    tracks the fleet over time and no single scaled total is shown here."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._costs = merged_vehicle_costs( plans )
        for ci, cost in enumerate( self._costs ):
            amount = MoneyField( required = False, min_value = 0 )
            amount.initial = cost.amount
            amount.widget.attrs[ 'aria-label' ] = f'{cost.name} — per vehicle'
            self.fields[ self._amount_key( ci ) ] = amount
            add_cadence_fields( self, self._cad_prefix( ci ), cost.interval, cost.cadence_domain )

    @staticmethod
    def _amount_key( ci : int ) -> str:
        return f'amount_{ci}'

    @staticmethod
    def _cad_prefix( ci : int ) -> str:
        return f'cad_{ci}'

    @property
    def rows( self ) -> list:
        """One row per running cost: its name, the per-car amount field, and its cadence control."""
        return [ {
            'name'    : cost.name,
            'amount'  : self[ self._amount_key( ci ) ],
            'cadence' : cadence_cells( self, self._cad_prefix( ci ), cost.interval, cost.cadence_domain ) }
            for ci, cost in enumerate( self._costs ) ]

    def apply( self, profile, plans ):
        costs = [ self._edited( ci, cost ) for ci, cost in enumerate( self._costs ) ]
        plan  = replace( vehicle_plan_of( plans ) or VehiclePlan(), running_costs = costs )
        return profile, replace( plans, vehicle_plan = plan if plan_has_content( plan ) else None )

    def _edited( self, ci : int, cost ) -> VehicleRunningCost:
        """`cost` with its per-car amount and cadence re-read from this row's fields."""
        interval = read_cadence( self, self._cad_prefix( ci ), cost.interval, cost.cadence_domain )
        amount   = self.cleaned_data.get( self._amount_key( ci ) )
        return replace( cost, interval = interval, amount = amount )
