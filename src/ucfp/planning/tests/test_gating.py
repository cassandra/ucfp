"""Scenario gating: `scenario_started` and the three-way `partition_scenarios` split.

Setting up the Profile auto-creates a Default scenario, so a never-touched scenario is "in progress"
only by construction. `scenario_started` keys off whether the user has reviewed any Plans or Assumptions
step, so the forecast gate offers only a genuinely worked-on scenario to resume -- not the Default the
user never chose to build. `partition_scenarios` then splits an org's scenarios into complete,
drift-blocked (runnable but for stale Plans->Profile references), and in-progress.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.planning.gating import partition_scenarios, scenario_started
from ucfp.planning.tests.support import expected_assumptions, forecast_profile


def _started( plans_keys, assumptions_keys ):
    return SimpleNamespace(
        plans       = SimpleNamespace( acknowledged_section_keys = plans_keys ),
        assumptions = SimpleNamespace( acknowledged_section_keys = assumptions_keys ) )


class ScenarioStartedTests( unittest.TestCase ):

    def test_untouched_default_is_not_started( self ):
        self.assertFalse( scenario_started( _started( set(), set() ) ) )

    def test_a_reviewed_plans_step_counts_as_started( self ):
        self.assertTrue( scenario_started( _started( { 'living-expenses' }, set() ) ) )

    def test_a_reviewed_assumptions_step_counts_as_started( self ):
        self.assertTrue( scenario_started( _started( set(), { 'external-factors' } ) ) )


def _reviewed_keys_by_flow( profile ):
    """The keys of every applicable, form-backed section, grouped by the flow that owns each -- so a
    record can mark exactly its own sections reviewed and the three together cover the whole interview."""
    by_flow = { 'profile': [], 'plans': [], 'assumptions': [] }
    for section in applicable_sections( profile ):
        if section.form is not None:
            by_flow[ flow_of( section ) ].append( section.key )
    return by_flow


def _drifted_plans():
    """Plans holding a repayment for a debt the profile does not have."""
    return Plans( loan_repayments = [ LoanRepayment(
        debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
        remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] )


class PartitionScenariosTests( TestCase ):
    """`partition_scenarios` splits an org's scenarios three ways -- complete, drift-blocked (runnable but
    for stale references), and in-progress -- against the current profile."""

    def setUp( self ):
        call_command( 'seed_parameter_sets' )        # expected_assumptions reads a seeded outlook
        self.organization = Organization.objects.create( name = 'Org' )
        self.profile      = forecast_profile()
        self.keys         = _reviewed_keys_by_flow( self.profile )
        record = save_profile( self.organization, self.profile )
        record.acknowledged_sections = self.keys[ 'profile' ]
        record.save()
        self.profile_record = record

    def _scenario( self, label, plans_schema, reviewed = True ):
        plans_record = PlansRecord(
            organization = self.organization, label = f'{label} P',
            acknowledged_sections = self.keys[ 'plans' ] if reviewed else [] )
        save_plans( plans_record, plans_schema )
        assumptions_record = AssumptionsRecord(
            organization = self.organization, label = f'{label} A',
            acknowledged_sections = self.keys[ 'assumptions' ] if reviewed else [] )
        save_assumptions( assumptions_record, expected_assumptions() )
        return create_scenario( self.organization, plans_record, assumptions_record, label )

    def test_a_reviewed_undrifted_scenario_is_complete( self ):
        scenario = self._scenario( 'Runnable', Plans() )
        complete, drift_blocked, in_progress = partition_scenarios( self.organization, self.profile_record )
        self.assertIn( scenario.uuid, [ s.uuid for s in complete ] )
        self.assertEqual( ( drift_blocked, in_progress ), ( [], [] ) )

    def test_a_drift_only_scenario_is_drift_blocked( self ):
        # A scenario blocked only by drift is bucketed apart from the half-built; the stale references and
        # the reconcile route are the shared `inputs.drift` notice's job (tested there).
        scenario = self._scenario( 'Foo', _drifted_plans() )
        _complete, drift_blocked, in_progress = partition_scenarios( self.organization, self.profile_record )
        self.assertEqual( in_progress, [] )
        self.assertEqual( [ s.uuid for s in drift_blocked ], [ scenario.uuid ] )

    def test_a_half_built_scenario_is_in_progress( self ):
        scenario = self._scenario( 'Half', Plans(), reviewed = False )
        _complete, drift_blocked, in_progress = partition_scenarios( self.organization, self.profile_record )
        self.assertEqual( drift_blocked, [] )
        self.assertIn( scenario.uuid, [ s.uuid for s in in_progress ] )

    def test_drift_plus_incompleteness_is_in_progress_not_drift_blocked( self ):
        # Reconcile alone would not make it runnable (a step is still unreviewed), so it stays in-progress.
        scenario = self._scenario( 'Both', _drifted_plans(), reviewed = False )
        _complete, drift_blocked, in_progress = partition_scenarios( self.organization, self.profile_record )
        self.assertEqual( drift_blocked, [] )
        self.assertIn( scenario.uuid, [ s.uuid for s in in_progress ] )
