"""The External Factors (§8) editor's Social Security funding fields: the benefits-payable percent and
the effective year seed, round-trip, and validate, and survive alongside the growth-rate factors.

The engine behaviour of the reduction is tested in `forecast/tests/test_income.py`; here we cover the
input layer -- that the two knobs reach the stored economics unharmed.
"""
import unittest
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.test import SimpleTestCase

from common.date_window import DateWindow
from common.rate import Rate
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.defaults import DEFAULT_TAX_FORECAST_TYPE
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.external_factors import ECONOMIC_FACTORS, ExternalFactorsForm

_PAYABLE = 'social_security_benefits_payable'
_YEAR    = 'social_security_reduction_year'


def _seed() -> EconomicParameters:
    """A plain economics seed (zero rates, 100% benefits payable, 2032) -- avoids the DB-backed preset so
    the form logic is tested in isolation."""
    return EconomicParameters()


def _data( economics, **overrides ):
    """A full valid POST for the form, seeded from `economics`, with any field overridden."""
    data = QueryDict( mutable = True )
    for factor in ECONOMIC_FACTORS:
        data[ factor.field ] = str( getattr( economics, factor.field ).fraction * 100 )
    data[ _YEAR ]         = str( economics.social_security_reduction_year )
    data[ 'forecast_type' ] = DEFAULT_TAX_FORECAST_TYPE.name.lower()
    for name, value in overrides.items():
        data[ name ] = str( value )
    return data


class ExternalFactorsFundingTests( SimpleTestCase ):

    def _apply( self, **overrides ):
        economics = _seed()
        form = ExternalFactorsForm(
            _data( economics, **overrides ), assumptions = Assumptions( economics = economics ) )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, assumptions = form.apply( None, Assumptions( economics = economics ) )
        return assumptions.economics

    def test_it_seeds_the_funding_fields_from_economics( self ):
        form = ExternalFactorsForm( assumptions = Assumptions( economics = _seed() ) )
        self.assertEqual( form[ _PAYABLE ].value(), Decimal( '100' ) )   # whole percent, no decimals
        self.assertEqual( form[ _YEAR ].value(), 2032 )

    def test_it_round_trips_the_funding_fields_through_apply( self ):
        economics = self._apply( **{ _PAYABLE: 75, _YEAR: 2035 } )
        self.assertEqual( economics.social_security_benefits_payable, Rate.percent( Decimal( '75' ) ) )
        self.assertEqual( economics.social_security_reduction_year, 2035 )

    def test_apply_preserves_funding_alongside_a_rate_edit( self ):
        economics = self._apply( inflation = 4, **{ _PAYABLE: 80 } )
        self.assertEqual( economics.inflation, Rate.percent( Decimal( '4' ) ) )               # the rate edit
        self.assertEqual( economics.social_security_benefits_payable, Rate.percent( Decimal( '80' ) ) )
        self.assertEqual( economics.social_security_reduction_year, 2032 )                    # year untouched

    def test_apply_preserves_the_unedited_window( self ):
        # the reason apply replaces onto the seed rather than building fresh: fields the form never
        # edits (the outlook window) must survive a save.
        window    = DateWindow( start = date( 2030, 1, 1 ) )
        seed      = EconomicParameters( window = window )
        form      = ExternalFactorsForm( _data( seed ), assumptions = Assumptions( economics = seed ) )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, assumptions = form.apply( None, Assumptions( economics = seed ) )
        self.assertEqual( assumptions.economics.window, window )

    def test_benefits_payable_is_bounded_to_0_100( self ):
        for bad in ( 150, -10 ):
            economics = _seed()
            form = ExternalFactorsForm(
                _data( _seed(), **{ _PAYABLE: bad } ), assumptions = Assumptions( economics = economics ) )
            self.assertFalse( form.is_valid() )
            self.assertIn( _PAYABLE, form.errors )

    def test_the_effective_year_is_bounded( self ):
        economics = _seed()
        form = ExternalFactorsForm(
            _data( economics, **{ _YEAR: 1999 } ), assumptions = Assumptions( economics = economics ) )
        self.assertFalse( form.is_valid() )
        self.assertIn( _YEAR, form.errors )


if __name__ == '__main__':
    unittest.main()
