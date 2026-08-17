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

from common.forms import MoneyField
from ucfp.accounts.enums import AssetClass

from .plans.defaults import DRAW_SOURCE_CLASSES, SWEEP_TARGET_CLASSES, default_drawdown
from .plans.schemas import DrawdownPolicy


# Draw-source row labels for the pane. Real-estate classes carry a verbose "Real Estate (...)" catalog
# label, so the pane shows the shorter group name -- plural where the household may hold several (to
# match the Profile panes), singular for the one primary residence. Every other source (the liquid
# classes, the possessions) reads well as its own label, so it falls through to that.
_DRAW_SOURCE_LABELS = {
    AssetClass.REAL_ESTATE_RESIDENCE   : 'Residence',
    AssetClass.REAL_ESTATE_SECOND_HOME : 'Second Homes',
    AssetClass.REAL_ESTATE_RENTAL      : 'Rentals',
}


def _draw_source_label( asset_class : AssetClass ) -> str:
    return _DRAW_SOURCE_LABELS.get( asset_class, asset_class.label )


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

    cash_floor   = MoneyField( label = 'Minimum cash', min_value = 0 )
    cash_ceiling = MoneyField( label = 'Maximum cash', min_value = 0, required = False )

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._profile = profile
        self._policy  = (
            plans.drawdown if ( plans is not None and plans.drawdown is not None ) else default_drawdown() )
        self.fields[ 'cash_floor' ].initial   = self._policy.cash_floor
        self.fields[ 'cash_ceiling' ].initial = self._policy.cash_ceiling

    # ---- draw order ----
    #
    # One ordered list holds every source; `retained` marks the ones held back. Both persist, so a
    # retained source keeps its slot (re-enabling restores its priority). The pane posts the full order
    # (`draw_order`) plus the retained names (`retained`); materialization drops the retained before the
    # engine, which therefore only ever iterates the enabled sources.

    @property
    def draw_rows( self ) -> list:
        """Every draw source in priority order: its post value, group label, whether the household holds
        it, whether it is enabled (drawn) or retained, and its 1-based draw rank -- numbered across the
        enabled rows only (a retained row has no rank), so the badge always reads as true draw priority.
        Any source the stored order predates is surfaced at the end, enabled."""
        held     = { asset.asset_class for asset in ( self._profile.assets if self._profile else () ) }
        retained = set( self._policy.retained )
        order    = list( self._policy.draw_order )
        order   += [ c for c in DRAW_SOURCE_CLASSES if c not in order ]
        rows     = list()
        rank     = 0
        for source in order:
            enabled = source not in retained
            rank   += 1 if enabled else 0
            rows.append( { 'value' : source.name, 'label' : _draw_source_label( source ),
                           'held' : source in held, 'enabled' : enabled,
                           'rank' : rank if enabled else None } )
        return rows

    def _submitted( self, field_name ) -> list:
        by_name = { c.name : c for c in DRAW_SOURCE_CLASSES }
        return [ by_name[ name ] for name in self.data.getlist( field_name ) if name in by_name ]

    def _submitted_order( self ) -> list:
        return self._submitted( 'draw_order' ) or list( self._policy.draw_order )

    def _submitted_retained( self ) -> list:
        # Bounded to what the posted order actually contains -- a retained name with no matching row is
        # meaningless, and dropping it keeps `retained` a clean subset of `draw_order`.
        order = set( self._submitted_order() )
        return [ source for source in self._submitted( 'retained' ) if source in order ]

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
            retained         = self._submitted_retained(),
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
