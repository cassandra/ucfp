"""The selling-costs editor: the transaction costs applied when a property is sold.

A Selling costs sub-pane of the Advanced Assumptions page, distinct from the economic outlook: the
realtor commission (a percent of the sale price) and the fixed costs (title/escrow/transfer, entered in
today's dollars and inflation-adjusted to the sale year by the engine). Seeded from the assumptions or
the shared default; materialization reads the copy stored here.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import MoneyField, PercentField
from common.rate import Rate

from ucfp.forecast.parameters import TransactionCosts

from .assumptions.defaults import default_transaction_costs


class TransactionCostsForm( forms.Form ):
    """The selling-costs editor: seeded from the assumptions (or the shared default), `apply` stores the
    edited costs back on the assumptions."""

    realtor_fee = PercentField( label = 'Realtor fee' )        # percent of the sale price
    fixed_cost  = MoneyField( label = 'Other fixed costs' )    # dollars, in forecast-start terms

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
