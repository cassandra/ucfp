"""The external-factors section: the assumptions' economic-factors copy and the tax projection.

§8 shows the assumptions' own copy of the economic rates (seeded from a library preset, Expected by
default) and lets the user edit any rate; the tax projection is shown as one more factor, defaulting
to COLA-indexed. Each rate is entered as a percent. The default seed and the tax-projection
composition are shared with minting through `assumptions.defaults` -- materialization reads the copy
stored here, not the library.
"""
from dataclasses import dataclass, fields, replace
from decimal import Decimal

from django import forms

from common.forms import PercentField
from common.rate import Rate

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.jurisdiction.enums import StatuteForecastType

from .assumptions.defaults import DEFAULT_TAX_FORECAST_TYPE, default_economics, tax_projection


@dataclass( frozen = True )
class _Factor:
    """One economic factor as the user sees it: the engine `EconomicParameters` field it edits, a human
    `label`, and a one-line `help`. Presentation only -- decoupled from the engine field order."""
    field : str
    label : str
    help  : str


# The economic factors grouped and ordered deliberately for the pane -- the most-adjusted "what-if"
# knobs first, then income/benefit growth, yields, and niche asset rates. This ordering, the labels, and
# the help live here (the input layer), not on the engine dataclass. Every rate factor of
# `EconomicParameters` appears exactly once (asserted below), so the form and `apply` are complete.
_FACTOR_GROUPS = (
    ( 'Inflation & growth', (
        _Factor( 'inflation', 'Inflation',
                 'General price inflation -- drives expense growth and the tax-bracket indexing below.' ),
        _Factor( 'stock_appreciation', 'Stock / market appreciation',
                 'Annual price growth of stocks and dividend stocks.' ),
        _Factor( 'real_estate_appreciation', 'Real-estate appreciation',
                 'Annual value growth of homes, second homes, and rental property.' ),
        _Factor( 'wage_growth', 'Wage growth',
                 'Annual raise rate applied to employment income.' ),
        _Factor( 'retirement_growth', 'Retirement-account growth',
                 'Blended annual growth of pre-tax and Roth retirement accounts.' ) ) ),
    ( 'Income & benefits growth', (
        _Factor( 'social_security_cola', 'Social Security annual increase',
                 'Yearly cost-of-living increase on Social Security benefits.' ),
        _Factor( 'pension_cola', 'Pension annual increase',
                 'Yearly increase on pension income, where one applies.' ),
        _Factor( 'rental_increase', 'Rental-income increase',
                 'Annual growth of gross rental income.' ),
        _Factor( 'medical_inflation', 'Medical inflation',
                 'Inflation on medical and health-insurance costs, usually above general inflation.' ) ) ),
    ( 'Social Security funding', (
        _Factor( 'social_security_benefits_payable', 'Social Security benefits payable',
                 'Retained share of scheduled Social Security benefits if the trust-fund shortfall is not '
                 'addressed (commonly cited around 75%). 100% assumes no reduction.' ), ) ),
    ( 'Interest & yields', (
        _Factor( 'savings_interest', 'Savings interest',
                 'Yield on cash and savings balances.' ),
        _Factor( 'cd_interest', 'CD interest',
                 'Yield on certificates of deposit.' ),
        _Factor( 'bond_interest', 'Bond interest',
                 'Coupon yield paid by bonds.' ),
        _Factor( 'stock_dividend', 'Stock dividend yield',
                 'Dividend yield on dividend stocks.' ),
        _Factor( 'bond_appreciation', 'Bond appreciation',
                 'Price growth of bonds -- typically near zero, since the return is the coupon.' ) ) ),
    ( 'Other assets', (
        _Factor( 'precious_metals_appreciation', 'Precious-metals appreciation',
                 'Annual value growth of gold, silver, and similar.' ),
        _Factor( 'collectibles_appreciation', 'Collectibles appreciation',
                 'Annual value growth of art, jewelry, and similar collectibles.' ),
        _Factor( 'depreciation_rate', 'Vehicle depreciation',
                 'Annual value lost by depreciating personal property -- vehicles.' ) ) ),
)

# The flat factor list in display order, and a fail-fast guard that the curated spec covers exactly the
# engine's rate factors (the non-rate `window` is excluded -- it stays at its default constant outlook).
_ALL_FACTORS  = tuple( factor for _group, factors in _FACTOR_GROUPS for factor in factors )
_FACTOR_NAMES = tuple( factor.field for factor in _ALL_FACTORS )

# The economic factors in display order, shared with the Explore workspace's economic section so its
# rate dials carry the same fields and labels as this editor (each `_Factor` exposes `field` and `label`).
ECONOMIC_FACTORS = _ALL_FACTORS
_ENGINE_RATE_FIELDS = frozenset(
    spec.name for spec in fields( EconomicParameters ) if isinstance( spec.default, Rate ) )
assert set( _FACTOR_NAMES ) == _ENGINE_RATE_FIELDS, (
    'external-factors spec is out of step with EconomicParameters rate fields: '
    f'{set( _FACTOR_NAMES ) ^ _ENGINE_RATE_FIELDS}' )


class ExternalFactorsForm( forms.Form ):
    """§8 -- the assumptions' editable economic factors (seeded from a preset) and the tax projection
    (one more factor, defaulting to COLA-indexed). Each rate is entered as a percent; `apply` stores
    the factor copy and the tax forecast on the assumptions."""

    forecast_type = forms.ChoiceField(
        label = 'Future tax brackets', choices = StatuteForecastType.choices(),
        initial = DEFAULT_TAX_FORECAST_TYPE.name.lower(),
        widget = forms.Select( attrs = { 'class' : 'custom-select w-auto' } ) )

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        super().__init__( data, initial = self._initial( assumptions ) )
        economics = self._seed( assumptions )
        for factor in _ALL_FACTORS:
            field = PercentField( label = factor.label )
            field.initial = getattr( economics, factor.field ).fraction * Decimal( '100' )
            self.fields[ factor.field ] = field

    @staticmethod
    def _seed( assumptions ) -> EconomicParameters:
        if assumptions is not None and assumptions.economics is not None:
            return assumptions.economics
        return default_economics()

    @staticmethod
    def _initial( assumptions ) -> dict:
        if assumptions is not None and assumptions.tax_projection is not None:
            return { 'forecast_type': assumptions.tax_projection.forecast_type.name.lower() }
        return dict()

    @property
    def factor_groups( self ) -> list:
        """The factors grouped in display order for the pane -- each group's label and its rows
        (label, help, and bound field)."""
        return [ { 'label': group,
                   'factors': [ { 'label': factor.label, 'help': factor.help,
                                  'field': self[ factor.field ] }
                                for factor in factors ] }
                 for group, factors in _FACTOR_GROUPS ]

    def apply( self, profile, assumptions ):
        # replace onto the seed (not a fresh build) so the non-rate economics fields the form does not
        # edit -- the funding effective year, the window -- are preserved across a save.
        economics = replace( self._seed( assumptions ), **{
            factor.field: Rate.percent( self.cleaned_data[ factor.field ] ) for factor in _ALL_FACTORS } )
        tax_type = StatuteForecastType.from_name( self.cleaned_data[ 'forecast_type' ] )
        return profile, replace(
            assumptions, economics = economics,
            tax_projection = tax_projection( tax_type, economics ) )


class ExternalFactorsSectionForm:
    """§8 section wrapper. The External Factors pane self-saves through `ExternalFactorsView`, so this
    section form only carries the flow: it always validates and its `apply` is a no-op, leaving Next to
    advance without re-saving. It exposes the editor (`factors_form`) for the pane to render."""

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        self._profile     = profile
        self._assumptions = assumptions

    def is_valid( self ) -> bool:
        return True

    @property
    def factors_form( self ) -> ExternalFactorsForm:
        return ExternalFactorsForm( profile = self._profile, assumptions = self._assumptions )

    def apply( self, profile, assumptions ):
        return profile, assumptions
