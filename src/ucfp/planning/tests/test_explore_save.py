"""SaveView's POST mapping -- the Save-changes modal's `save_mode` (plus per-component `dest_*`) translated
into the one `save_working` primitive. 'update' overwrites both components into the anchor in place (no new
scenario); 'new' branches a scenario named `name`, each component copied or reusing the source's set. This
pins the view-level translation the modal depends on; `save_working`'s own behavior is covered in
test_exploration.
"""
from decimal import Decimal

from django.core.management import call_command
from django.http import QueryDict
from django.test import RequestFactory, TestCase

from organization.models import Organization

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.models import AssumptionsRecord, PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import DrawdownPolicy, Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.scenarios.exploration import enter_exploration, overwrite_working
from ucfp.inputs.scenarios.repository import create_scenario, load_scenario, scenarios_for
from ucfp.inputs.scenarios.schemas import Scenario
from ucfp.session_state import SessionState
from ucfp.planning.views import SaveView

from .support import expected_assumptions, forecast_profile


def _tweaked_plans() -> Plans:
    """A Plans distinct from the anchor's empty `Plans()`, so a persisted tweak is detectable -- a complete
    drawdown policy (bounds, order, and allocation), which round-trips through the component sets."""
    return Plans( drawdown = DrawdownPolicy(
        cash_floor = Decimal( '25000' ), cash_ceiling = Decimal( '50000' ),
        draw_order = [ AssetClass.CDS, AssetClass.BONDS, AssetClass.STOCKS ],
        sweep_allocation = [ ( 'stocks', Decimal( '0.6' ) ), ( 'bonds', Decimal( '0.4' ) ) ] ) )


class SaveViewMappingTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.organization = Organization.objects.create( name = 'Org' )
        save_profile( self.organization, forecast_profile() )
        self.source  = self._saved( 'Source' )
        self.factory = RequestFactory()
        enter_exploration( self.organization, self.source )
        overwrite_working(                                             # tweak the sandbox away from the anchor
            self.organization, Scenario( plans = _tweaked_plans(), assumptions = expected_assumptions() ) )

    def _saved( self, label ):
        plans = save_plans( PlansRecord( organization = self.organization, label = f'{label} plans' ), Plans() )
        assumptions = save_assumptions(
            AssumptionsRecord( organization = self.organization, label = f'{label} assumptions' ),
            expected_assumptions() )
        return create_scenario( self.organization, plans, assumptions, label )

    def _save( self, **post ):
        """Drive SaveView.post with the modal's posted fields."""
        data = QueryDict( mutable = True )
        data.update( post )
        request = self.factory.post( '/save', data )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = {}
        return SaveView().post( request )

    def _reload( self, record ):
        """A fresh read of a scenario record -- an in-place overwrite mutates the shared component set, so
        the setup's cached object would still hold stale content."""
        return scenarios_for( self.organization ).get( uuid = record.uuid )

    def test_update_overwrites_the_anchor_in_place_without_branching( self ):
        before = { record.uuid for record in scenarios_for( self.organization ) }
        self._save( save_mode = 'update' )
        after = { record.uuid for record in scenarios_for( self.organization ) }
        self.assertEqual( after, before )                                                 # no new scenario
        self.assertEqual( load_scenario( self._reload( self.source ) ).plans, _tweaked_plans() )   # anchor took it

    def test_new_copies_the_changed_component_and_reuses_the_unchanged_one( self ):
        # Only Plans was tweaked in setUp; Assumptions matches the anchor. Saving as new copies the changed
        # Plans (branch owns it, anchor keeps its own) and reuses the unchanged Assumptions (shared set).
        self._save( save_mode = 'new', name = 'Branch' )
        branches = [ record for record in scenarios_for( self.organization ) if record.label == 'Branch' ]
        self.assertEqual( len( branches ), 1 )
        branch, source = branches[ 0 ], self._reload( self.source )
        self.assertEqual( load_scenario( branch ).plans, _tweaked_plans() )   # the branch holds the tweak...
        self.assertEqual( load_scenario( source ).plans, Plans() )            # ...and the anchor is untouched
        self.assertNotEqual( branch.plans_id, source.plans_id )               # changed Plans -> an own copy
        self.assertEqual( branch.assumptions_id, source.assumptions_id )      # unchanged Assumptions -> shared

    def test_missing_save_mode_updates_in_place_rather_than_branching( self ):
        # The modal always posts save_mode, but the mapping must default a blank to 'update' rather than
        # silently branching -- 'new' is the only value that creates a scenario.
        before = { record.uuid for record in scenarios_for( self.organization ) }
        self._save()
        self.assertEqual( { record.uuid for record in scenarios_for( self.organization ) }, before )
        self.assertEqual( load_scenario( self._reload( self.source ) ).plans, _tweaked_plans() )
