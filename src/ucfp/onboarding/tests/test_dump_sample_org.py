"""`dump_sample_org`: export a complete organization's latest Profile + a saved scenario's Plans/Assumptions
to a plaintext fixture, and refuse an incomplete (non-runnable) source."""
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.onboarding.constants import SAMPLE_ORGANIZATION_NAME, SAMPLE_ORGANIZATION_UUID
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.tests.support import expected_assumptions, forecast_profile


def _reviewed_keys_by_flow( profile ):
    """The applicable form-backed section keys grouped by flow -- so each record marks exactly its own
    sections reviewed and the three together complete the interview (a scenario then runs)."""
    by_flow = { 'profile': [], 'plans': [], 'assumptions': [] }
    for section in applicable_sections( profile ):
        if section.form is not None:
            by_flow[ flow_of( section ) ].append( section.key )
    return by_flow


def _runnable_scenario( organization, *, reviewed = True ):
    """A complete, runnable scenario for `organization`: a completed profile plus reviewed Plans and
    Assumptions (mirrors the gating tests' construction)."""
    profile = forecast_profile()
    keys = _reviewed_keys_by_flow( profile )
    profile_record = save_profile( organization, profile )
    profile_record.acknowledged_sections = keys[ 'profile' ]
    profile_record.save()

    plans_record = PlansRecord(
        organization = organization, label = 'P',
        acknowledged_sections = keys[ 'plans' ] if reviewed else [] )
    save_plans( plans_record, Plans() )
    assumptions_record = AssumptionsRecord(
        organization = organization, label = 'A',
        acknowledged_sections = keys[ 'assumptions' ] if reviewed else [] )
    save_assumptions( assumptions_record, expected_assumptions() )
    scenario = create_scenario( organization, plans_record, assumptions_record, 'Runnable' )
    return profile_record, scenario


def _dump( organization, output ):
    call_command( 'dump_sample_org', '--org', str( organization.uuid ), '--output', output, verbosity = 0 )


class DumpSampleOrgTest( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()                        # expected_assumptions reads a seeded outlook

    def test_dumps_the_three_payloads_with_review_state( self ):
        organization = Organization.objects.create( name = 'Source' )
        profile_record, scenario = _runnable_scenario( organization )
        with tempfile.TemporaryDirectory() as tmp:
            path = str( Path( tmp ) / 'out.json' )
            _dump( organization, path )
            payload = json.load( open( path ) )

        self.assertEqual( set( payload ), { 'profile', 'plans', 'assumptions' } )
        for section in ( 'profile', 'plans', 'assumptions' ):
            self.assertEqual( set( payload[ section ] ), { 'data', 'acknowledged_sections' } )
        # Payloads are the records' decrypted data + their review state.
        self.assertEqual( payload[ 'profile' ][ 'data' ], profile_record.data )
        self.assertEqual(
            payload[ 'profile' ][ 'acknowledged_sections' ], profile_record.acknowledged_sections )
        self.assertEqual( payload[ 'plans' ][ 'data' ], scenario.plans.data )
        self.assertEqual( payload[ 'assumptions' ][ 'data' ], scenario.assumptions.data )

    def test_default_resolves_the_sample_org_by_reserved_uuid( self ):
        # No --org: the reserved uuid wins even when the org is named something else.
        organization = Organization.objects.create( name = 'Renamed', uuid = SAMPLE_ORGANIZATION_UUID )
        _runnable_scenario( organization )
        with tempfile.TemporaryDirectory() as tmp:
            path = str( Path( tmp ) / 'out.json' )
            call_command( 'dump_sample_org', '--output', path, verbosity = 0 )
            self.assertEqual( set( json.load( open( path ) ) ), { 'profile', 'plans', 'assumptions' } )

    def test_default_falls_back_to_the_sample_org_name( self ):
        # No org carries the reserved uuid, but one is named 'Sample Household' -> found by name.
        organization = Organization.objects.create( name = SAMPLE_ORGANIZATION_NAME )
        _runnable_scenario( organization )
        with tempfile.TemporaryDirectory() as tmp:
            path = str( Path( tmp ) / 'out.json' )
            call_command( 'dump_sample_org', '--output', path, verbosity = 0 )
            self.assertEqual( set( json.load( open( path ) ) ), { 'profile', 'plans', 'assumptions' } )

    def test_default_errors_when_no_sample_household_exists( self ):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises( CommandError ):
            call_command( 'dump_sample_org', '--output', str( Path( tmp ) / 'out.json' ), verbosity = 0 )

    def test_refuses_an_organization_with_no_completed_profile( self ):
        bare = Organization.objects.create( name = 'Bare' )  # no profile at all -> nothing runnable
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises( CommandError ):
            _dump( bare, str( Path( tmp ) / 'out.json' ) )

    def test_refuses_an_unrunnable_scenario( self ):
        organization = Organization.objects.create( name = 'Half' )
        _runnable_scenario( organization, reviewed = False )  # completed profile, half-built scenario
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises( CommandError ):
            _dump( organization, str( Path( tmp ) / 'out.json' ) )
