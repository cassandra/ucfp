"""The scenario-build screen -- the form -> typed `Scenario` -> repository round-trip, now
driven by the seeded parameter-set library (the outlook/lifestyle selects).

`/scenario/` resolves the scenario the user is working on -- the one selected in the session,
else the latest, else a fresh one -- and redirects to its detail page. `/scenario/<uuid>/`
renders the single-page form (pre-populated from the scenario), marks it the current scenario,
and on POST materializes the typed `Scenario` and saves it.
"""
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from user.decorators import ensure_organization

from .forms import ScenarioBuildForm
from .models import ScenarioRecord
from .repository import create_scenario, latest_scenario, load_scenario, save_scenario
from .view_mixins import ScenarioViewMixin

_TEMPLATE = 'scenario/pages/scenario_detail.html'


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioHomeView( View ):
    """`/scenario/` -- land on the current scenario (session), else the latest, else a new one."""

    def get( self, request ):
        return redirect( 'scenario_detail', scenario_uuid = self._resolve( request ).uuid )

    def _resolve( self, request ) -> ScenarioRecord:
        selected_uuid = request.session_state.current_scenario_uuid
        if selected_uuid is not None:
            current = ScenarioRecord.objects.filter(
                uuid = selected_uuid, organization = request.organization ).first()
            if current is not None:
                return current
        return latest_scenario( request.organization ) or create_scenario( request.organization )


@method_decorator( ensure_organization, name = 'dispatch' )
class ScenarioDetailView( ScenarioViewMixin, View ):
    """`/scenario/<uuid>/` -- the single-page scenario form; POST saves the typed scenario."""

    def get( self, request, *args, **kwargs ):
        record = self.get_scenario( request, *args, **kwargs )
        self._select( request, record )
        return render( request, _TEMPLATE, {
            'form': ScenarioBuildForm( scenario = load_scenario( record ) ) } )

    def post( self, request, *args, **kwargs ):
        record = self.get_scenario( request, *args, **kwargs )
        form = ScenarioBuildForm( request.POST )
        if form.is_valid():
            save_scenario( record, form.to_scenario() )
            return redirect( 'scenario_detail', scenario_uuid = record.uuid )
        return render( request, _TEMPLATE, { 'form': form } )

    def _select( self, request, record ):
        request.session_state.current_scenario_uuid = str( record.uuid )
        request.session_state.to_session( request )
