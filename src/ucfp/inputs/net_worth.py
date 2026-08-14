"""The net-worth section: the assumed tax rates that adjust reported net worth toward realizable wealth.

A small Assumptions-flow section, sibling to Selling Costs: the two rates the Estimated Future Taxes
overlay applies -- the ordinary rate on pre-tax retirement balances (taxable in full on withdrawal), and
the capital-gains rate on unrealized investment gains. Both default to zero, which books no overlay and
leaves net worth gross, so the section is opt-in. Seeded from the assumptions or the shared (zero)
default; materialization reads the copy stored here.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import PercentField
from common.rate import Rate

from ucfp.forecast.parameters import NetWorthCalculation

from .assumptions.defaults import default_net_worth_calculation


class NetWorthForm( forms.Form ):
    """The net-worth rates editor: seeded from the assumptions (or the zero default), `apply` stores the
    edited rates back on the assumptions. Zero rates (the default) leave net worth gross."""

    ordinary_rate      = PercentField( label = 'Pre-tax retirement rate' )   # ordinary rate on withdrawal
    capital_gains_rate = PercentField( label = 'Unrealized gains rate' )     # cap-gains rate on the gain

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        super().__init__( data )
        rates = self._seed( assumptions )
        self.fields[ 'ordinary_rate' ].initial      = rates.ordinary_tax_rate.fraction * Decimal( '100' )
        self.fields[ 'capital_gains_rate' ].initial = rates.capital_gains_tax_rate.fraction * Decimal( '100' )

    @staticmethod
    def _seed( assumptions ) -> NetWorthCalculation:
        if assumptions is not None and assumptions.net_worth is not None:
            return assumptions.net_worth
        return default_net_worth_calculation()

    def apply( self, profile, assumptions ):
        rates = NetWorthCalculation(
            ordinary_tax_rate      = Rate.percent( self.cleaned_data[ 'ordinary_rate' ] ),
            capital_gains_tax_rate = Rate.percent( self.cleaned_data[ 'capital_gains_rate' ] ) )
        return profile, replace( assumptions, net_worth = rates )


class NetWorthSectionForm:
    """Section wrapper for the Net Worth pane. The pane self-saves through `NetWorthView`, so this only
    carries the flow: it always validates and its `apply` is a no-op, leaving Next to advance without
    re-saving. It exposes the editor (`net_worth_form`) for the pane to render."""

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        self._profile     = profile
        self._assumptions = assumptions

    def is_valid( self ) -> bool:
        return True

    @property
    def net_worth_form( self ) -> NetWorthForm:
        return NetWorthForm( profile = self._profile, assumptions = self._assumptions )

    def apply( self, profile, assumptions ):
        return profile, assumptions
