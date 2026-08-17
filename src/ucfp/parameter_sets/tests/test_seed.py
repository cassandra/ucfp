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
    CadenceDomain, CatalogScope, EconomicOutlookVariant, ExpenseCategory, ExpenseClass,
    ParameterSetKind, Realization )
from ucfp.parameter_sets.models import ParameterSet
from ucfp.parameter_sets.repository import economic_parameters, load
from ucfp.planning.materialization import ForecastFrame, materialize
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection

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
        segment = schedule.segments[ 0 ]
        self.assertEqual( segment.inflation.fraction, Decimal( '0.03' ) )
        # The niche asset rates seed non-zero (they previously fell through to a 0 default).
        self.assertEqual( segment.precious_metals_appreciation.fraction, Decimal( '0.03' ) )
        self.assertEqual( segment.collectibles_appreciation.fraction, Decimal( '0.02' ) )
        self.assertEqual( segment.depreciation_rate.fraction, Decimal( '0.18' ) )

    def test_load_returns_the_expense_catalog( self ):
        call_command( 'seed_parameter_sets' )
        catalog = load( ParameterSetKind.EXPENSE_CATALOG, CatalogScope.GENERAL.label )
        # A deliberate tripwire -- bump this when the catalog gains or loses an expense, so an
        # accidental change to the seeded set is caught.
        self.assertEqual( len( catalog.expenses ), 42 )
        food = next( expense for expense in catalog.expenses if expense.name == 'Food' )
        self.assertEqual( food.default_amount, Decimal( '170' ) )
        # Two groupings place a row: its applicability class (which surface) and its visual category
        # (the ordered section), with an explicit item order within the category.
        self.assertEqual( food.expense_class, ExpenseClass.LIVING )
        self.assertEqual( food.category, ExpenseCategory.EVERYDAY )
        self.assertEqual( food.order, 10 )
        # The cadence attributes seed too: Food is a smoothed weekly/monthly consumable, while a
        # property tax is a discrete bill the user may re-express monthly or yearly.
        self.assertEqual( food.realization, Realization.SMOOTH )
        self.assertEqual( food.cadence_domain, CadenceDomain.WK_MO )
        tax = next( expense for expense in catalog.expenses if expense.name == 'Property Tax' )
        self.assertEqual( tax.expense_class, ExpenseClass.PROPERTY )
        self.assertEqual( tax.category, ExpenseCategory.TAXES_INSURANCE )
        self.assertEqual( tax.realization, Realization.DISCRETE )
        self.assertEqual( tax.cadence_domain, CadenceDomain.MO_YR )
        # A durable (count-entry) row carries its calculator breakdown; its amount is the annualized
        # cost, count x cost_each / lifespan.
        appliance = next( expense for expense in catalog.expenses if expense.name == 'Appliance' )
        self.assertEqual( appliance.count, 3 )
        self.assertEqual( appliance.cost_each, Decimal( '2900' ) )
        self.assertEqual( appliance.lifespan, 15 )
        self.assertEqual( appliance.default_amount, Decimal( '580' ) )   # 3 x 2900 / 15


class MaterializeFromLibraryTest( TestCase ):

    def test_materialize_resolves_the_outlook_and_the_engine_runs( self ):
        call_command( 'seed_parameter_sets' )
        profile = Profile(
            subjects = [ SubjectProfile(
                handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            # The $0 Stocks/Bonds accounts are the always-seeded sweep homes (see the Accounts step):
            # the default drawdown policy sweeps surplus into them, so they must exist as holdings.
            assets = [
                AssetProfile(
                    handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                    opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) ),
                AssetProfile(
                    handle = 'stocks', name = 'Stocks', asset_class = AssetClass.STOCKS,
                    opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ),
                AssetProfile(
                    handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                    opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ) ] )
        plans = Plans()
        assumptions = Assumptions(   # the economic-factors copy, seeded here
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            tax_projection = TaxProjection(
                forecast_type = StatuteForecastType.CURRENT_LAW ) )
        params = materialize(
            profile = profile, plans = plans, assumptions = assumptions,
            frame = ForecastFrame( start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ) ) )
        self.assertEqual(
            params.economic_outlook.parameters_at( date( 2026, 1, 1 ) ).inflation.fraction,
            Decimal( '0.03' ) )
        self.assertEqual( type( Forecast( params ).run() ).__name__, 'ForecastResult' )
