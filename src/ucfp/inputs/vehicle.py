"""§ Vehicle Expenses -- the car-purchase pane.

INTERIM (#84 Phase 1): the household's cars moved from a single shared purchase pattern to a list of
per-vehicle entries (each with its own purchase/end dates, price, recurrence, and financing) on the
`VehiclePlan`. Phase 2 replaces this pane with the per-vehicle "Add a vehicle" list (mirroring the
Property list). Until then this is a no-op placeholder so the Vehicle Expenses section still loads --
the per-car running-costs pane continues to work in the meantime.
"""
from django import forms


class VehiclePlanForm( forms.Form ):
    """Placeholder for the car-purchase pane during the per-vehicle rework (#84). Carries no fields and
    its `apply` leaves Plans untouched; the real per-vehicle list arrives in Phase 2."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )

    def apply( self, profile, plans ):
        return profile, plans
