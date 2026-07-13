"""The transaction-costs section: the selling costs applied when an asset is sold.

A small Assumptions-flow section, distinct from the economic outlook: the realtor commission (a percent
of the sale price) and the fixed costs (title/escrow/transfer, entered in today's dollars and
inflation-adjusted to the sale year by the engine). Seeded from the assumptions or the shared default;
materialization reads the copy stored here.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.rate import Rate

from ucfp.forecast.parameters import TransactionCosts

from .assumptions.defaults import default_transaction_costs


class TransactionCostsForm( forms.Form ):
    """The selling-costs editor: seeded from the assumptions (or the shared default), `apply` stores the
    edited costs back on the assumptions."""

    realtor_fee = forms.DecimalField( label = 'Realtor fee' )        # percent of the sale price
    fixed_cost  = forms.DecimalField( label = 'Other fixed costs' )  # dollars, in forecast-start terms

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        super().__init__( data )
        costs = self._seed( assumptions )
        self.fields[ 'realtor_fee' ].initial = costs.property_sale_realtor_fee_rate.fraction * Decimal( '100' )
        self.fields[ 'fixed_cost' ].initial  = costs.property_sale_fixed_cost

    @staticmethod
    def _seed( assumptions ) -> TransactionCosts:
        if assumptions is not None and assumptions.transaction_costs is not None:
            return assumptions.transaction_costs
        return default_transaction_costs()

    def apply( self, profile, assumptions ):
        costs = TransactionCosts(
            property_sale_realtor_fee_rate = Rate.percent( self.cleaned_data[ 'realtor_fee' ] ),
            property_sale_fixed_cost       = self.cleaned_data[ 'fixed_cost' ] )
        return profile, replace( assumptions, transaction_costs = costs )


class TransactionCostsSectionForm:
    """Section wrapper for the Selling Costs pane. The pane self-saves through `TransactionCostsView`, so
    this only carries the flow: it always validates and its `apply` is a no-op, leaving Next to advance
    without re-saving. It exposes the editor (`costs_form`) for the pane to render."""

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        self._profile     = profile
        self._assumptions = assumptions

    def is_valid( self ) -> bool:
        return True

    @property
    def costs_form( self ) -> TransactionCostsForm:
        return TransactionCostsForm( profile = self._profile, assumptions = self._assumptions )

    def apply( self, profile, assumptions ):
        return profile, assumptions
