"""The Cash Plan section: the cash band and how the engine keeps the hub inside it.

A Plans-flow section. `cash_floor`/`cash_ceiling` are the band; `draw_order` is the priority of
liquid asset classes the engine sells when cash runs low -- an up/down-ordered list, shown over the
full liquid set (even types not yet held, so the order survives new holdings). The sweep (investing
surplus above the ceiling) is added in a later section. Seeded from the plan's drawdown policy or
the shared default; materialization reads the copy stored here.
"""
from dataclasses import replace

from django import forms

from .plans.defaults import LIQUID_DRAW_CLASSES, default_drawdown
from .plans.schemas import DrawdownPolicy


class DrawdownForm( forms.Form ):
    """The cash-band editor: the min/max cash and the draw-order priority over the liquid classes.
    Seeded from the plan's drawdown policy (or the default); `apply` stores the edited policy back
    on the plans, preserving the sweep allocation (which a later section sets)."""

    cash_floor   = forms.DecimalField(
        label = 'Minimum cash', min_value = 0,
        widget = forms.NumberInput( attrs = { 'class' : 'form-control' } ) )
    # Disabled until the sweep step: the engine requires a ceiling to come with a sweep allocation
    # (a destination to invest the surplus into), so the maximum is set together with the sweep.
    cash_ceiling = forms.DecimalField(
        label = 'Maximum cash', min_value = 0, required = False, disabled = True,
        widget = forms.NumberInput( attrs = { 'class' : 'form-control' } ) )

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._profile = profile
        self._policy  = (
            plans.drawdown if ( plans is not None and plans.drawdown is not None ) else default_drawdown() )
        self.fields[ 'cash_floor' ].initial = self._policy.cash_floor

    @property
    def draw_rows( self ) -> list:
        """The draw-order rows for the pane: every liquid class in priority order (the stored order,
        then any not yet placed), each flagged with whether the household holds it."""
        held  = { asset.asset_class for asset in ( self._profile.assets if self._profile else () ) }
        order = [ c for c in self._policy.draw_order if c in LIQUID_DRAW_CLASSES ]
        order += [ c for c in LIQUID_DRAW_CLASSES if c not in order ]
        return [ { 'value' : c.name, 'label' : c.label, 'held' : c in held } for c in order ]

    def _submitted_order( self ) -> list:
        """The draw order as posted -- the hidden `draw_order` inputs in their (reordered) DOM order,
        filtered to the known liquid classes. Falls back to the current order if none was posted."""
        by_name  = { c.name : c for c in LIQUID_DRAW_CLASSES }
        ordered  = [ by_name[ name ] for name in self.data.getlist( 'draw_order' ) if name in by_name ]
        return ordered or list( self._policy.draw_order )

    def apply( self, profile, plans ):
        sweep = list( self._policy.sweep_allocation )                    # preserved; set in a later section
        policy = DrawdownPolicy(
            cash_floor       = self.cleaned_data[ 'cash_floor' ],
            # A ceiling is kept only when a sweep exists to invest the surplus (the engine requires the
            # pair). Until the sweep step sets both, the maximum stays None -- an inert band max, not an
            # invalid ceiling.
            cash_ceiling     = self._policy.cash_ceiling if sweep else None,
            draw_order       = self._submitted_order(),
            sweep_allocation = sweep )
        return profile, replace( plans, drawdown = policy )


class CashPlanSectionForm:
    """Section wrapper for the Cash Plan pane. The pane self-saves through `CashPlanView`, so this
    only carries the flow: it is always valid, its `apply` is a no-op (Next just advances), and it
    exposes the editor (`drawdown_form`) for the pane to render."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile = profile
        self._plans   = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def drawdown_form( self ) -> DrawdownForm:
        return DrawdownForm( profile = self._profile, plans = self._plans )

    def apply( self, profile, plans ):
        return profile, plans
