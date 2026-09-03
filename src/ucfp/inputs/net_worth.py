"""The Net worth calculation section of the Advanced page: the opt-in estimate that adjusts reported net
worth toward realizable (after-tax) wealth.

By default net worth is assets minus liabilities at face value, but pre-tax retirement balances and
unrealized investment gains carry a latent tax that comes due on withdrawal or sale, so the naive figure
overstates what is realizable. These two assumed rates -- the latent ordinary rate on pre-tax retirement
balances and the latent capital-gains rate on unrealized gains -- let the Estimated Future Taxes overlay
subtract an estimate of that embedded tax. Both default to zero, which books no overlay and leaves net
worth gross, so the section is opt-in. Seeded from the assumptions or the shared (zero) default;
materialization reads the copy stored here.
"""
from dataclasses import replace
from decimal import Decimal

from django import forms

from common.forms import PercentField
from common.rate import Rate

from ucfp.forecast.parameters import NetWorthCalculation

from .assumptions.defaults import default_net_worth_calculation


class NetWorthForm( forms.Form ):
    """The Net worth calculation editor: the two latent-tax rates the Estimated Future Taxes overlay
    applies to estimate the tax embedded in pre-tax retirement balances and unrealized gains. Seeded from
    the assumptions (or the zero default), `apply` stores the edited rates back. Zero rates (the default)
    leave net worth gross."""

    ordinary_rate      = PercentField( label = 'Latent ordinary tax rate' )        # on pre-tax retirement
    capital_gains_rate = PercentField( label = 'Latent capital-gains tax rate' )   # on unrealized gains

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
