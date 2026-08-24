"""DashboardView rendering: the signed-in dashboard renders each forecast-overview state end to end.

The state logic itself is covered by `planning.tests.test_forecast_overview`; these tests exercise the
template path -- the overview-card include, the reused `scenario_required` pane, the `money` filter, and
the feature icons -- so a broken include or filter is caught, not just the view-model.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.models import Organization

from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.repository import load_profile, save_profile
from ucfp.inputs.scenarios.repository import create_scenario
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.planning.enums import PlanningFeature
from ucfp.planning.models import PlanningResultRecord
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.tests.support import expected_assumptions, forecast_frame, forecast_profile

User = get_user_model()


class DashboardViewTests( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()
        self.user = User.objects.create_user( email = 'owner@x.test', password = 'x' )
        self.org  = Organization.objects.create_for_owner( self.user, name = 'Mine' )
        self.client.force_login( self.user )

    def _get( self ):
        return self.client.get( reverse( 'dashboard' ) )

    def _complete_profile( self ):
        keys   = [ section.key for section in applicable_sections( forecast_profile() )
                   if section.form is not None and flow_of( section ) == 'profile' ]
        record = save_profile( self.org, forecast_profile() )
        record.acknowledged_sections = keys
        record.save()
        return record

    def _half_scenario( self ):
        plans = save_plans( PlansRecord( organization = self.org, label = 'P' ), Plans() )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.org, label = 'A' ), expected_assumptions() )
        return create_scenario( self.org, plans, assumptions, 'Half' )

    def _saved_run( self, label = 'Example Forecast', source_label = 'Example Scenario' ):
        profile = load_profile( save_profile( self.org, forecast_profile() ) )
        run = run_and_capture(
            organization = self.org, profile = profile, plans = Plans(),
            assumptions = expected_assumptions(), frame = forecast_frame(),
            label = label, source_label = source_label )
        return PlanningResultRecord.objects.create(
            organization = self.org, feature = PlanningFeature.FINANCIAL_FORECAST,
            run = run, label = label, usage_role = UsageRole.SAVED )

    def test_needs_profile_renders_the_profile_prompt( self ):
        response = self._get()
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'set up your profile' )
        self.assertContains( response, 'Overview' )                 # the page heading
        self.assertContains( response, '<title>Dashboard · Landfall</title>', html = False )

    def test_needs_scenario_renders_the_reused_scenario_pane( self ):
        self._complete_profile()
        self._half_scenario()
        response = self._get()
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Future Scenario' )          # from the shared scenario_required pane

    def test_has_run_renders_the_kpi_card( self ):
        self._saved_run( label = 'Example Forecast', source_label = 'Example Scenario' )
        response = self._get()
        self.assertEqual( response.status_code, 200 )
        # The recap leads with the run's name, then its source -- not the source in place of the name.
        self.assertContains( response, 'Example Forecast' )
        self.assertContains( response, 'from Example Scenario' )
        self.assertContains( response, 'Ending net worth' )         # a KPI tile
        # The net-worth sparkline renders in place of the old placeholder.
        self.assertContains( response, 'forecast-chart__svg' )
        self.assertContains( response, '<polyline' )
        self.assertContains( response, reverse( 'run_results', args = [ self._latest_run_uuid() ] ) )

    def test_coming_soon_features_render_as_placeholders( self ):
        response = self._get()
        # Named placeholders (reserved for future summaries), styled by the inert card class.
        self.assertContains( response, 'overview-soon-card' )
        self.assertContains( response, 'Retirement Timing' )
        self.assertContains( response, 'Social Security' )
        self.assertContains( response, 'Cash Flow' )

    def _latest_run_uuid( self ):
        return PlanningResultRecord.objects.get( organization = self.org ).run.uuid
