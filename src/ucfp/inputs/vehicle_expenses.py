"""The per-car vehicle running costs of the Vehicle Expenses step.

The household's car running costs (fuel, insurance, maintenance, repair) are entered once *per car* and
scaled by the vehicle plan's shared `num_cars`. They are seeded from the curated catalog's `VEHICLE`
rows and stored on the `VehiclePlan` (alongside the purchase/financing pattern), not with the general
recurring expenses -- a shared-quantity shape distinct from the independent, per-age recurring costs.
This module seeds those costs from the catalog, preserving amounts and cadences already set.
"""
from ucfp.parameter_sets.enums import ExpenseCategory
from ucfp.inputs.plans.schemas import VehicleRunningCost
from ucfp.inputs.expenses import kept_interval, load_catalog


def merged_vehicle_costs( plans ) -> list:
    """The catalog's `VEHICLE` rows as `VehicleRunningCost`s -- each existing per-car amount (and any
    chosen cadence) preserved, missing ones seeded at the catalog default. The tax class and realization
    are re-derived from the catalog each merge (not user edits)."""
    existing = ( { cost.name: cost for cost in plans.vehicle_plan.running_costs }
                 if plans is not None and plans.vehicle_plan is not None else dict() )
    merged = list()
    for catalog_expense in load_catalog().expenses:
        if catalog_expense.category is not ExpenseCategory.VEHICLE:
            continue
        prior = existing.get( catalog_expense.name )
        merged.append( VehicleRunningCost(
            name = catalog_expense.name,
            expense_tax_class = catalog_expense.expense_tax_class,
            interval = kept_interval( prior, catalog_expense ),
            realization = catalog_expense.realization,
            cadence_domain = catalog_expense.cadence_domain,
            amount = prior.amount if prior is not None else catalog_expense.default_amount ) )
    return merged
