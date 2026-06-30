"""The parameter-set seed lifecycle, the load path, and the end-to-end resolution at
materialize -- the non-trivial mechanism that has to behave exactly on re-runs and app updates.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from ucfp.accounts.enums import AssetClass
from ucfp.forecast.forecast import Forecast
from ucfp.parameter_sets.enums import (
    CatalogScope, EconomicOutlookVariant, ExpenseCategory, LifestyleLevel, LifestyleScope,
    ParameterSetKind )
from ucfp.parameter_sets.models import ParameterSet
from ucfp.parameter_sets.repository import economic_parameters, load
from ucfp.planning.materialization import ForecastFrame, materialize
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.inputs.plans.schemas import LifestylePlan, LifestyleSegment, Plans
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile

_ECON     = ParameterSetKind.ECONOMIC_OUTLOOK
_EXPECTED = EconomicOutlookVariant.EXPECTED.label


def _system_set( name ):
    return ParameterSet.objects.get( kind = _ECON, label = name, organization = None )


class SeedLifecycleTest( TestCase ):

    def test_seed_creates_the_named_presets( self ):
        call_command( 'seed_parameter_sets' )
        names = set( ParameterSet.objects.filter(
            kind = _ECON, organization = None ).values_list( 'label', flat = True ) )
        self.assertEqual( names, { variant.label for variant in EconomicOutlookVariant } )
        record = _system_set( _EXPECTED )
        self.assertEqual( record.data, record.seeded_data )
        self.assertFalse( record.is_modified )

    def test_reseed_is_idempotent( self ):
        call_command( 'seed_parameter_sets' )
        count = ParameterSet.objects.count()
        call_command( 'seed_parameter_sets' )
        self.assertEqual( ParameterSet.objects.count(), count )

    def test_reseed_preserves_admin_modifications( self ):
        call_command( 'seed_parameter_sets' )
        record = _system_set( _EXPECTED )
        record.data = { 'segments': [] }
        record.save()
        self.assertTrue( record.is_modified )
        call_command( 'seed_parameter_sets' )
        record.refresh_from_db()
        self.assertEqual( record.data, { 'segments': [] } )

    def test_reseed_refreshes_an_untouched_but_stale_default( self ):
        call_command( 'seed_parameter_sets' )
        record = _system_set( _EXPECTED )
        stale = { 'segments': [] }
        ParameterSet.objects.filter( pk = record.pk ).update( data = stale, seeded_data = stale )
        call_command( 'seed_parameter_sets' )
        record.refresh_from_db()
        self.assertNotEqual( record.data, stale )
        self.assertEqual( record.data, record.seeded_data )

    def test_force_refreshes_even_modified_defaults( self ):
        call_command( 'seed_parameter_sets' )
        record = _system_set( _EXPECTED )
        record.data = { 'segments': [] }
        record.save()
        call_command( 'seed_parameter_sets', '--force' )
        record.refresh_from_db()
        self.assertNotEqual( record.data, { 'segments': [] } )
        self.assertFalse( record.is_modified )


class LoadPathTest( TestCase ):

    def test_load_returns_the_typed_schedule( self ):
        call_command( 'seed_parameter_sets' )
        schedule = load( _ECON, _EXPECTED )
        self.assertEqual( len( schedule.segments ), 1 )
        self.assertEqual( schedule.segments[ 0 ].inflation.fraction, Decimal( '0.025' ) )

    def test_load_returns_the_expense_catalog( self ):
        call_command( 'seed_parameter_sets' )
        catalog = load( ParameterSetKind.EXPENSE_CATALOG, CatalogScope.GENERAL.label )
        self.assertEqual( len( catalog.expenses ), 39 )
        food = next( expense for expense in catalog.expenses if expense.name == 'Food' )
        self.assertEqual( food.default_amount, Decimal( '150' ) )
        self.assertEqual( food.category, ExpenseCategory.EVERYDAY )
        self.assertTrue( food.lifestyle_dependent )


class MaterializeFromLibraryTest( TestCase ):

    def test_materialize_resolves_the_outlook_and_the_engine_runs( self ):
        call_command( 'seed_parameter_sets' )
        profile = Profile(
            subjects = [ SubjectProfile(
                handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            assets = [ AssetProfile(
                handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) ) ] )
        plans = Plans()
        assumptions = Assumptions(   # the economic-factors copy, seeded here
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            statute = StatuteProfile(
                jurisdiction_type = JurisdictionType.US_FEDERAL,
                forecast_type = StatuteForecastType.CURRENT_LAW ) )
        params = materialize(
            profile = profile, plans = plans, assumptions = assumptions,
            frame = ForecastFrame( start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ) ) )
        self.assertEqual(
            params.economic_outlook.parameters_at( date( 2026, 1, 1 ) ).inflation.fraction,
            Decimal( '0.025' ) )
        self.assertEqual( type( Forecast( params ).run() ).__name__, 'ForecastResult' )

    def test_lifestyle_table_resolves_into_stepped_streams_and_items( self ):
        call_command( 'seed_parameter_sets' )
        profile = Profile(
            subjects = [ SubjectProfile(
                handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            assets = [ AssetProfile(
                handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                opening_value = Decimal( '900000' ), cost_basis = Decimal( '900000' ) ) ] )
        plans = Plans(
            lifestyle = LifestylePlan(
                scope = LifestyleScope.GENERAL,
                segments = [
                    LifestyleSegment( start = date( 2026, 1, 1 ), level = LifestyleLevel.LOW ),
                    LifestyleSegment( start = date( 2030, 1, 1 ), level = LifestyleLevel.HIGH ) ] ) )
        assumptions = Assumptions(
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            statute = StatuteProfile(
                jurisdiction_type = JurisdictionType.US_FEDERAL,
                forecast_type = StatuteForecastType.CURRENT_LAW ) )
        params = materialize(
            profile = profile, plans = plans, assumptions = assumptions,
            frame = ForecastFrame( start_date = date( 2026, 1, 1 ), end_date = date( 2031, 12, 31 ) ) )
        self.assertIn( 'Home Insurance', { s.name for s in params.expense_streams } )   # a stream
        item_names = { i.name for i in params.expense_items }
        self.assertIn( 'Gas', item_names )                                              # an item
        self.assertIn( 'Automobile Purchase', item_names )
        gas = next( item for item in params.expense_items if item.name == 'Gas' )
        stepped = [ segment.amount for segment in gas.amounts.segments ]
        self.assertEqual( stepped, [ Decimal( '10' ), Decimal( '50' ) ] )               # low -> high
        self.assertEqual( type( Forecast( params ).run() ).__name__, 'ForecastResult' )
