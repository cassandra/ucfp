"""The Cash Plan section: the cash band, the draw-order priority, and the sweep of surplus.

A Plans-flow section. `cash_floor`/`cash_ceiling` are the band; `draw_order` is the priority of
liquid asset classes the engine sells when cash runs low (an up/down-ordered list); the sweep is a
weighted split of the surplus above the ceiling across non-retirement holdings. Seeded from the
plan's drawdown policy or the shared default; materialization reads the copy stored here. The engine
requires a ceiling to come with a sweep, so the two are edited together and stored as a pair -- a
ceiling with no sweep yet is simply not persisted (non-blocking), never re-rendered from under typing.
"""
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from django import forms

from .plans.defaults import LIQUID_DRAW_CLASSES, SWEEP_TARGET_CLASSES, default_drawdown
from .plans.schemas import DrawdownPolicy


def _normalized( rows : list ) -> list:
    """`(handle, weight)` rows (positive weights) -> `(handle, fraction)` summing to exactly 1. The
    last row absorbs the rounding remainder so `AssetAllocation`'s sum-to-one check always holds."""
    total   = sum( ( weight for _handle, weight in rows ), Decimal( '0' ) )
    running = Decimal( '0' )
    result  = list()
    for index, ( handle, weight ) in enumerate( rows ):
        if index < len( rows ) - 1:
            fraction = ( weight / total ).quantize( Decimal( '0.000001' ) )
            running += fraction
        else:
            fraction = Decimal( '1' ) - running
        result.append( ( handle, fraction ) )
    return result


class DrawdownForm( forms.Form ):
    """The cash-policy editor: the band, the draw-order priority, and the sweep of surplus. Seeded
    from the plan's drawdown policy (or the default); `apply` stores the edited policy back on the
    plans. A ceiling is kept only when a sweep names where to invest the surplus."""

    cash_floor   = forms.DecimalField(
        label = 'Minimum cash', min_value = 0,
        widget = forms.NumberInput( attrs = { 'class' : 'form-control' } ) )
    cash_ceiling = forms.DecimalField(
        label = 'Maximum cash', min_value = 0, required = False,
        widget = forms.NumberInput( attrs = { 'class' : 'form-control' } ) )

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._profile = profile
        self._policy  = (
            plans.drawdown if ( plans is not None and plans.drawdown is not None ) else default_drawdown() )
        self.fields[ 'cash_floor' ].initial   = self._policy.cash_floor
        self.fields[ 'cash_ceiling' ].initial = self._policy.cash_ceiling

    # ---- draw order ----

    @property
    def draw_rows( self ) -> list:
        """The draw-order rows for the pane: every liquid class in priority order (the stored order,
        then any not yet placed), each flagged with whether the household holds it."""
        held  = { asset.asset_class for asset in ( self._profile.assets if self._profile else () ) }
        order = [ c for c in self._policy.draw_order if c in LIQUID_DRAW_CLASSES ]
        order += [ c for c in LIQUID_DRAW_CLASSES if c not in order ]
        return [ { 'value' : c.name, 'label' : c.label, 'held' : c in held } for c in order ]

    def _submitted_order( self ) -> list:
        by_name = { c.name : c for c in LIQUID_DRAW_CLASSES }
        ordered = [ by_name[ name ] for name in self.data.getlist( 'draw_order' ) if name in by_name ]
        return ordered or list( self._policy.draw_order )

    # ---- sweep ----

    @property
    def sweep_targets( self ) -> list:
        """The holdings a sweep may invest into -- the non-retirement liquid holdings, always present
        (the Accounts step keeps a $0 account for each). The row selects choose among these."""
        return [ { 'handle' : asset.handle, 'label' : asset.asset_class.label }
                 for asset in ( self._profile.assets if self._profile else () )
                 if asset.asset_class in SWEEP_TARGET_CLASSES ]

    @property
    def sweep_rows( self ) -> list:
        """The current sweep as pane rows (target handle, whole-percent weight); one blank row when
        there is no sweep yet, so the table always shows an editable line."""
        rows = [ { 'handle' : handle, 'weight' : ( weight * 100 ).quantize( Decimal( '1' ) ) }
                 for handle, weight in self._policy.sweep_allocation ]
        return rows or [ { 'handle' : '', 'weight' : '' } ]

    def _submitted_sweep( self ) -> list:
        """Posted sweep rows -> `(handle, weight)` for valid target handles with a positive weight."""
        valid   = { target[ 'handle' ] for target in self.sweep_targets }
        handles = self.data.getlist( 'sweep_handle' )
        weights = self.data.getlist( 'sweep_weight' )
        rows    = list()
        for handle, weight in zip( handles, weights ):
            if ( handle not in valid ) or ( not weight.strip() ):
                continue
            try:
                amount = Decimal( weight )
            except InvalidOperation:
                continue
            if amount > 0:
                rows.append( ( handle, amount ) )
        return rows

    def apply( self, profile, plans ):
        ceiling = self.cleaned_data.get( 'cash_ceiling' )
        rows    = self._submitted_sweep() if ceiling is not None else list()
        sweep   = _normalized( rows ) if rows else list()
        policy  = DrawdownPolicy(
            cash_floor       = self.cleaned_data[ 'cash_floor' ],
            cash_ceiling     = ceiling if sweep else None,   # a ceiling is kept only with a sweep to invest into
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
