"""The Economics section and the Advanced page's economics editors: the assumptions' editable
economic-factors copy (the rate outlook).

The main Economics pane shows the broadly-applicable rates (seeded from a library preset, Expected by
default), grouped on a single axis. Niche rates -- applicable only to a specific, less-common holding or
income -- move to the Advanced page's Economics subsection to keep the common outlook uncluttered; the
Social Security funding what-if and the future-tax-bracket projection are on Advanced too (funding here,
the bracket projection in `taxes.py`). Each rate is entered as a percent. The default seed and the
tax-projection composition are shared with minting through `assumptions.defaults` -- materialization
reads the copy stored here, not the library.

Every economics editor edits the *same* economics copy, each replacing only its own subset of rate fields
and preserving the rest, so the panes compose without clobbering one another. Because a COLA-indexed
projection is indexed at the outlook's inflation, the main pane recomposes the stored `tax_projection` on
every save so an inflation edit keeps the projection in step; the niche and funding editors do not touch
inflation, so they leave the projection alone.
"""
from dataclasses import dataclass, fields, replace
from decimal import Decimal
from typing import Optional

from django import forms

from common.forms import PercentField
from common.rate import Rate

from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.jurisdiction.enums import StatuteForecastType

from .assumptions.defaults import DEFAULT_TAX_FORECAST_TYPE, default_economics, tax_projection


@dataclass( frozen = True )
class _Factor:
    """One economic factor as the user sees it: the engine `EconomicParameters` field it edits, a human
    `label`, and a one-line `help`. Presentation only -- decoupled from the engine field order. The
    optional bounds mark a *bounded share* (0-100%, whole) apart from an open-ended growth rate, and are
    honoured wherever the factor is edited (the Economics panes and the Explore dials) -- one source, no
    per-field branch."""
    field          : str
    label          : str
    help           : str
    min_value      : Optional[ int ] = None
    max_value      : Optional[ int ] = None
    decimal_places : Optional[ int ] = None

    def percent_field( self, *, required : bool = True ) -> PercentField:
        """A `PercentField` for editing this factor, carrying its bounds (unbounded for a growth rate)."""
        bounds = { name : value for name, value in (
            ( 'min_value', self.min_value ), ( 'max_value', self.max_value ),
            ( 'decimal_places', self.decimal_places ) ) if value is not None }
        return PercentField( label = self.label, required = required, **bounds )

    def seeded_initial( self, economics ) -> Decimal:
        """The factor's initial percent, seeded from `economics` -- a whole percent for a bounded share."""
        percent = getattr( economics, self.field ).fraction * Decimal( '100' )
        return percent.quantize( Decimal( '1' ) ) if self.decimal_places == 0 else percent


# The Social Security funding-shortfall knobs (edited on the Advanced page's Social Security funding
# sub-pane). The benefits-payable share is an ordinary percent factor (so it still rides the shared factor
# list into the Explore dials); the effective year is a bespoke integer.
_FUNDING_PAYABLE_FIELD = 'social_security_benefits_payable'
_FUNDING_YEAR_FIELD    = 'social_security_reduction_year'
_FUNDING_YEAR_LABEL    = 'Effective year'
_FUNDING_FACTOR = _Factor(
    _FUNDING_PAYABLE_FIELD, 'Social Security benefits payable',
    'Retained share of scheduled Social Security benefits if the trust-fund shortfall is not addressed '
    '(commonly cited around 75%). 100% assumes no reduction.',
    min_value = 0, max_value = 100, decimal_places = 0 )


# The main Economics-pane rate factors grouped on a single axis -- what each rate applies to -- so the
# taxonomy reads coherently. Only the broadly-applicable rates: inflation, then the common asset growth,
# the interest-and-yield distributions, then income growth. The labels and help live here (the input
# layer), not on the engine dataclass.
_FACTOR_GROUPS = (
    ( 'Inflation', (
        _Factor( 'inflation', 'Inflation',
                 'General price inflation -- drives expense growth and the tax-bracket indexing.' ),
        _Factor( 'medical_inflation', 'Medical inflation',
                 'Inflation on medical and health-insurance costs, usually above general inflation.' ) ) ),
    ( 'Growth & appreciation', (
        _Factor( 'stock_appreciation', 'Stock / market appreciation',
                 'Annual price growth of stocks and dividend stocks.' ),
        _Factor( 'real_estate_appreciation', 'Real-estate appreciation',
                 'Annual value growth of homes, second homes, and rental property.' ),
        _Factor( 'retirement_growth', 'Retirement-account growth',
                 'Blended annual growth of pre-tax and Roth retirement accounts.' ) ) ),
    ( 'Interest & yields', (
        _Factor( 'savings_interest', 'Savings interest',
                 'Yield on cash and savings balances.' ),
        _Factor( 'cd_interest', 'CD interest',
                 'Yield on certificates of deposit.' ),
        _Factor( 'bond_interest', 'Bond interest',
                 'Coupon yield paid by bonds.' ),
        _Factor( 'stock_dividend', 'Stock dividend yield',
                 'Dividend yield on dividend stocks.' ) ) ),
    ( 'Income growth', (
        _Factor( 'wage_growth', 'Wage growth',
                 'Annual raise rate applied to employment income.' ),
        _Factor( 'social_security_cola', 'Social Security annual increase',
                 'Yearly cost-of-living increase on Social Security benefits.' ),
        _Factor( 'pension_cola', 'Pension annual increase',
                 'Yearly increase on pension income, where one applies.' ) ) ),
)

# Niche economic rates -- applicable only to a specific, less-common holding or income -- shown on the
# Advanced page's Economics subsection, not the main pane, to keep the common outlook uncluttered.
_ADVANCED_ECONOMICS_FACTORS = (
    _Factor( 'bond_appreciation', 'Bond appreciation',
             'Price growth of bonds -- typically near zero, since the return is the coupon.' ),
    _Factor( 'precious_metals_appreciation', 'Precious-metals appreciation',
             'Annual value growth of gold, silver, and similar.' ),
    _Factor( 'collectibles_appreciation', 'Collectibles appreciation',
             'Annual value growth of art, jewelry, and similar collectibles.' ),
    _Factor( 'depreciation_rate', 'Vehicle depreciation',
             'Annual value lost by depreciating personal property -- vehicles.' ),
    _Factor( 'rental_increase', 'Rental-income increase',
             'Annual growth of gross rental income.' ),
)

# The main Economics-pane rate factors in display order -- shared with the Explore workspace's economic
# section, so its dials mirror the rates the Economics step shows. The canonical all-rates list adds the
# niche Advanced rates and the funding factor; a fail-fast guard holds it to exactly the engine's rate
# factors (the non-rate `window` is excluded), so every rate has a home somewhere in the UI.
ECONOMICS_SECTION_FACTORS = tuple( factor for _group, factors in _FACTOR_GROUPS for factor in factors )
ECONOMIC_FACTORS          = ECONOMICS_SECTION_FACTORS + _ADVANCED_ECONOMICS_FACTORS + ( _FUNDING_FACTOR, )
_ENGINE_RATE_FIELDS = frozenset(
    spec.name for spec in fields( EconomicParameters ) if isinstance( spec.default, Rate ) )
assert set( factor.field for factor in ECONOMIC_FACTORS ) == _ENGINE_RATE_FIELDS, (
    'economic-factors spec is out of step with EconomicParameters rate fields: '
    f'{set( factor.field for factor in ECONOMIC_FACTORS ) ^ _ENGINE_RATE_FIELDS}' )


def _seed_economics( assumptions ) -> EconomicParameters:
    """The economics copy an editor seeds from -- the assumptions' own, or the shared preset default."""
    if assumptions is not None and assumptions.economics is not None:
        return assumptions.economics
    return default_economics()


def _stored_forecast_type( assumptions ) -> StatuteForecastType:
    """The tax-bracket forecast type currently stored on the assumptions, or the default -- read by the
    Economics form so it can recompose the tax projection on a rate edit without owning the choice."""
    if assumptions is not None and assumptions.tax_projection is not None:
        return assumptions.tax_projection.forecast_type
    return DEFAULT_TAX_FORECAST_TYPE


class _EconomicRateForm( forms.Form ):
    """Base for a form editing a subset of the economic *rate* factors on the assumptions' economics copy.
    A subclass sets `_factors`; the base builds a seeded percent field per factor, and `_edited_economics`
    replaces just those edits onto the stored economics, preserving every field outside the subset (the
    window, the funding knobs, and the factors edited on other panes). Subclasses compose the returned
    assumptions in `apply`."""

    _factors : tuple = ()

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        super().__init__( data )
        economics = _seed_economics( assumptions )
        for factor in self._factors:
            field         = factor.percent_field()
            field.initial = factor.seeded_initial( economics )
            self.fields[ factor.field ] = field

    def _edited_economics( self, assumptions ) -> EconomicParameters:
        return replace(
            _seed_economics( assumptions ),
            **{ factor.field: Rate.percent( self.cleaned_data[ factor.field ] )
                for factor in self._factors } )

    @property
    def factor_rows( self ) -> list:
        """The factors as flat rows (label, help, bound field) -- for a pane that shows one ungrouped list."""
        return [ { 'label': factor.label, 'help': factor.help, 'field': self[ factor.field ] }
                 for factor in self._factors ]


class ExternalFactorsForm( _EconomicRateForm ):
    """The main Economics pane -- the assumptions' common economic rate factors, grouped on a single axis.
    Each rate is entered as a percent; `apply` stores the edited factor copy and recomposes the tax
    projection (COLA-indexed at the new inflation) from the stored forecast type, so an inflation edit
    keeps the projection in step. The niche rates, the forecast type, and the funding what-if are edited on
    the Advanced page, not here."""

    _factors = ECONOMICS_SECTION_FACTORS

    @property
    def factor_groups( self ) -> list:
        """The rate factors grouped in display order for the pane -- each group's label and its rows."""
        return [ { 'label': group,
                   'factors': [ { 'label': factor.label, 'help': factor.help, 'field': self[ factor.field ] }
                                for factor in factors ] }
                 for group, factors in _FACTOR_GROUPS ]

    def apply( self, profile, assumptions ):
        economics = self._edited_economics( assumptions )
        return profile, replace(
            assumptions, economics = economics,
            tax_projection = tax_projection( _stored_forecast_type( assumptions ), economics ) )


class AdvancedEconomicsForm( _EconomicRateForm ):
    """The Advanced page's Economics subsection -- the niche economic rates (bond appreciation, precious
    metals, collectibles, vehicle depreciation, rental-income increase) that apply only to specific,
    less-common holdings. Edits the same economics copy as the main pane; `apply` replaces just these rates
    and leaves the tax projection untouched (none of these drives its inflation indexing)."""

    _factors = _ADVANCED_ECONOMICS_FACTORS

    def apply( self, profile, assumptions ):
        return profile, replace( assumptions, economics = self._edited_economics( assumptions ) )


class ExternalFactorsSectionForm:
    """Economics section wrapper. The Economics pane self-saves through `ExternalFactorsView`, so this
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


class SocialSecurityFundingForm( forms.Form ):
    """The Advanced page's Social Security funding what-if: the retained share of scheduled benefits from
    the reduction year on, and the year it takes effect. Both edit the assumptions' economics copy; `apply`
    replaces them onto the stored economics, preserving every rate. Seeded from the assumptions or the
    shared preset default."""

    def __init__( self, data = None, *, profile = None, assumptions = None ):
        super().__init__( data )
        economics = _seed_economics( assumptions )
        payable   = _FUNDING_FACTOR.percent_field()
        payable.initial = _FUNDING_FACTOR.seeded_initial( economics )
        self.fields[ _FUNDING_PAYABLE_FIELD ] = payable
        self.fields[ _FUNDING_YEAR_FIELD ] = forms.IntegerField(
            label = _FUNDING_YEAR_LABEL, min_value = 2020, max_value = 2100,
            initial = economics.social_security_reduction_year,
            widget = forms.NumberInput( attrs = { 'class' : 'form-control' } ) )

    def apply( self, profile, assumptions ):
        economics = replace(
            _seed_economics( assumptions ),
            social_security_benefits_payable = Rate.percent( self.cleaned_data[ _FUNDING_PAYABLE_FIELD ] ),
            social_security_reduction_year   = self.cleaned_data[ _FUNDING_YEAR_FIELD ] )
        return profile, replace( assumptions, economics = economics )
