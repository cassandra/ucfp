from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.shortcuts import render, resolve_url
from django.utils.decorators import method_decorator
from django.views.generic import View

from common.exceptions import DataNotAvailableError

from custom.decorators import require_authentication_enabled

from user import collision
from user.signin_manager import SigninManager
from user.views import ConvertToGuestView

from ucfp.inputs.interview import first_section_of_flow
from ucfp.inputs.views import InterviewView

from ucfp.planning.enums import PlanningFeature
from ucfp.planning.models import PlanningResultRecord
from ucfp.planning.views import RunResultsView

from . import reconciliation_service
from .constants import EXAMPLE_ORGANIZATION_UUID, EXAMPLE_SCENARIO_UUID
from .membership import ensure_own_organization, join_example_org, example_organization


@method_decorator( require_authentication_enabled, name = 'dispatch' )
class SigninCollisionView( View ):
    """Reconcile a signed-in Guest's in-progress plan with an existing account they have just proved
    they own (the sign-in code hands off here via ``settings.SIGNIN_COLLISION_URL``).

    The Guest is still ``request.user`` -- the sign-in code deliberately did not switch accounts yet.
    A Guest with no plan of substance is silently superseded (adopt the existing account). Otherwise we
    show a side-by-side summary of the two plans and let the person keep their current work (re-homed
    onto the existing account), keep the existing account's plan instead, or decide later (stay a
    Guest, nothing lost). The target is read from the session; ``request.user`` is the Guest.
    """

    def get( self, request, *args, **kwargs ):
        target, guest = self._collision_parties( request )
        if target is None:
            return self._done( request )

        current = reconciliation_service.organization_summary(
            reconciliation_service.sole_organization( guest ) )
        if not current.has_content:
            # Nothing worth keeping: adopt the existing account without asking.
            reconciliation_service.discard_current_keep_previous( guest, target )
            collision.clear_collision_target( request )
            return self._sign_in( request, target )

        existing = reconciliation_service.organization_summary(
            reconciliation_service.sole_organization( target ) )
        # Each option is a card the person can pick directly: keeping the current work re-homes it onto
        # the existing account; keeping the existing account's plan discards the current work.
        return render( request, 'onboarding/signin_collision.html', {
            'options': [
                { 'label': 'Your current work', 'summary': current, 'choice': 'keep_current' },
                { 'label': 'Your existing account', 'summary': existing, 'choice': 'discard_current' },
            ],
        } )

    def post( self, request, *args, **kwargs ):
        target, guest = self._collision_parties( request )
        collision.clear_collision_target( request )
        if target is None:
            return self._done( request )

        choice = request.POST.get( 'choice' )
        if choice == 'keep_current':
            reconciliation_service.keep_current_discard_previous( guest, target )
            return self._sign_in( request, target )
        if choice == 'discard_current':
            reconciliation_service.discard_current_keep_previous( guest, target )
            return self._sign_in( request, target )
        # 'decide_later' (or anything unrecognized): leave the Guest and their plan exactly as they are.
        return self._done( request )

    @staticmethod
    def _collision_parties( request ):
        """The (target account, current Guest) the collision is between, or (None, guest) when there is
        no valid pending collision to resolve (stale/missing target, or the current user is not a Guest
        distinct from the target)."""
        guest = request.user
        target_uuid = collision.peek_collision_target( request )
        if ( target_uuid is None ) or ( not guest.is_authenticated ) or ( not guest.is_guest ):
            return None, guest
        target = get_user_model().objects.filter( uuid = target_uuid ).first()
        if ( target is None ) or ( target.pk == guest.pk ):
            return None, guest
        return target, guest

    def _sign_in( self, request, target ):
        request.user = target
        SigninManager().do_login( request = request )
        return self._done( request )

    @staticmethod
    def _done( request ):
        return HttpResponseRedirect( resolve_url( settings.LOGIN_REDIRECT_URL ) )


class StartTourView( ConvertToGuestView ):
    """Start the example-data tour ("Take a Tour"): join the visitor to the example organization, switch the
    session to it, and land on the tour. For an anonymous visitor a Guest is minted first (inherited from
    `ConvertToGuestView`); a signed-in visitor is used as-is -- no conversion and no blocking needed, since
    the tour pages are just the real org pages under a different wrapper and any read-only-ness comes from
    the visitor's (VIEWER) membership, not the tour. If the example org is not seeded there is nothing to
    tour."""

    def post( self, request, *args, **kwargs ):
        if example_organization() is None:
            raise DataNotAvailableError( 'Tour is currently unavailable' )
        return super().post( request, *args, **kwargs )

    def after_conversion( self, request, user ):
        join_example_org( user )                                # availability is guaranteed by post()'s guard
        request.session_state.set_current_organization( str( EXAMPLE_ORGANIZATION_UUID ) )
        request.session_state.to_session( request )
        return

    def landing_url( self, request ):
        return resolve_url( 'tour_profile', section = first_section_of_flow( 'profile' ).key )


class AddMyDataView( ConvertToGuestView ):
    """"Add My Data": the universal graduation from previewing the example to owning a plan. From an
    anonymous visitor it mints a Guest (inherited); then, for anyone, it ensures they are in an
    organization of their own -- not the read-only example -- and lands on the Profile (the inherited
    `GUEST_START_URL`) to start entering data. Offered wherever the example (or nothing) is all they have."""

    def after_conversion( self, request, user ):
        ensure_own_organization( request, user )
        return


class GoToOwnDashboardView( View ):
    """The home "Go to your dashboard" action for a user who has their own organization. Ensures the session
    is on that own org before landing on the dashboard: a visitor who reached Home from the tour still has
    the read-only example selected, and a CTA that says *your* dashboard must show their own data, not the
    example. `ensure_own_organization` leaves a deliberately chosen household alone and only corrects the
    example case, and the example stays reachable via the org switcher (membership in it is never revoked).
    POST-only, matching the other org-switch CTAs, so a crawled GET never mutates the session."""

    def post( self, request, *args, **kwargs ):
        ensure_own_organization( request, request.user )
        return HttpResponseRedirect( resolve_url( 'dashboard' ) )


# The tour's four-step backbone, numbered for the shell's step-nav (Profile -> Plans -> Assumptions ->
# Forecast). The three input flows map by name; the Forecast step is supplied by `TourForecastView`.
_TOUR_STEP_BY_FLOW = { 'profile': 1, 'plans': 2, 'assumptions': 3 }
_TOUR_STEP_FORECAST = 4


class TourInterviewView( InterviewView ):
    """Shared base for tour steps that reuse an interview flow (Profile, and Plans/Assumptions in scenario
    context): render the real interview under the tour shell, and keep navigation inside the tour -- the
    stepper, Next, and the async push_url all derive from `SECTION_URL_NAME`, which subclasses declare.
    Read-only-ness (if any) comes from the membership role, not the tour."""

    def _page_template( self, section ):
        return 'onboarding/tour/interview.html'

    def _context( self, request, sections, section, form ):
        """Add `tour_active_step` for the shell's step-nav. Keyed on the flow the parent already resolved,
        so the one scenario view lights Plans or Assumptions by which flow the visitor is looking at."""
        context = super()._context( request, sections, section, form )
        context[ 'tour_active_step' ] = _TOUR_STEP_BY_FLOW[ context[ 'flow' ] ]
        return context

    def _completion_destination( self, request, flow, building ):
        """The tour has no flow-completion destination: a last section shows no advance control (nothing to
        "Finish" while browsing; the four-step header moves between phases). This also keeps the read-only
        Finish from escaping to the app's Scenarios page, where the base sends a finished build/component."""
        return None


class TourProfileView( TourInterviewView ):
    """The Profile step of the tour."""

    SECTION_URL_NAME = 'tour_profile'


class TourScenarioView( TourInterviewView ):
    """The Plans + Assumptions step of the tour, in *scenario context* -- both parts in the left rail, the
    way a user meets them by default (rather than either in isolation). It sets the example scenario as the
    editing target so the two-part rail shows: a benign session write, since the tour is read-only and the
    interview's write side is POST, which the VIEWER role blocks. Both the Plans and Assumptions nav entries
    reach it at each flow's first section; the two-part rail switches between them."""

    SECTION_URL_NAME = 'tour_scenario'

    def get( self, request, section ):
        request.session_state.editing_scenario = str( EXAMPLE_SCENARIO_UUID )
        request.session_state.to_session( request )
        return super().get( request, section )


class TourForecastView( RunResultsView ):
    """The Forecast step of the tour: the captured example run's outcome summary and books table
    (`RunResultsView`) rendered under the tour shell. Unlike the run page it needs no run uuid in the URL --
    it resolves the example org's Financial Forecast run itself. The books-table column operations and the
    in-window Maximize keep working unchanged: the column op is a fragment swap (no navigation) and Maximize
    is pure client-side, so neither escapes the tour."""

    results_template = 'onboarding/tour/forecast.html'

    def _extra_context( self, request ) -> dict:
        return { 'tour_active_step': _TOUR_STEP_FORECAST }

    def get( self, request ):
        result = PlanningResultRecord.objects.filter(
            organization = request.organization, feature = PlanningFeature.FINANCIAL_FORECAST
        ).select_related( 'run' ).order_by( '-created_datetime' ).first()
        if result is None:
            raise DataNotAvailableError( 'The example forecast is not available.' )
        return super().get( request, run_uuid = result.run.uuid )
