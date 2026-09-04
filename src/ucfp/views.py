import json
from typing import Dict

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.generic import View

from common import antinode
from common.healthcheck import do_healthcheck
from common.request_utils import is_ajax

from ucfp.inputs.mixins import InputGatedMixin
from ucfp.planning.overview import forecast_overview
from ucfp.onboarding import reconciliation_service
from ucfp.onboarding.membership import example_organization, working_organization
from ucfp.privacy_consent import PrivacyConsent


def error_response( request             : HttpRequest,
                    sync_template_name  : str,
                    async_template_name : str,
                    status_code         : int,
                    force_json          : bool              = False,
                    context             : Dict[ str, str ]  = None ):
    """
    Helper routine for the similar error response functions.
    """
    if context is None:
        context = {}

    if 'error_message' not in context:
        context['error_message'] = 'Error (details missing).'
    if 'message' in context:
        context['error_message'] = context['message']

    if force_json or ( request.headers.get('accept', '') == 'application/json' ):
        return HttpResponse( json.dumps( context ),
                             content_type = "application/json",
                             status = status_code )

    if is_ajax( request ):
        response = antinode.modal_from_template( request,
                                                 async_template_name,
                                                 context )
    else:
        response = render( request, sync_template_name, context )

    response.status_code = status_code
    return response


def bad_request_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'Bad request.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/bad_request.html",
                           async_template_name = "modals/bad_request.html",
                           status_code = 400,
                           force_json = force_json,
                           context = context )


def improperly_configured_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'Improperly configured.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/improperly_configured.html",
                           async_template_name = "modals/improperly_configured.html",
                           status_code = 501,
                           force_json = force_json,
                           context = context )


def not_authorized_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'Not authorized.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/not_authorized.html",
                           async_template_name = "modals/not_authorized.html",
                           status_code = 403,
                           force_json = force_json,
                           context = context )


def method_not_allowed_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'Method not allowed.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/method_not_allowed.html",
                           async_template_name = "modals/method_not_allowed.html",
                           status_code = 405,
                           force_json = force_json,
                           context = context )


def page_not_found_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'Page not found.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/page_not_found.html",
                           async_template_name = "modals/page_not_found.html",
                           status_code = 404,
                           force_json = force_json,
                           context = context )


def internal_error_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'Internal error.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/internal_error.html",
                           async_template_name = "modals/internal_error.html",
                           status_code = 500,
                           force_json = force_json,
                           context = context )


def data_not_available_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'This data is not available yet.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/data_not_available.html",
                           async_template_name = "modals/data_not_available.html",
                           status_code = 404,
                           force_json = force_json,
                           context = context )


def transient_error_response( request, message : str = None, force_json : bool = False ):
    if not message:
        message = 'Transient error.'
    context = { 'message': message }
    return error_response( request = request,
                           sync_template_name = "pages/transient_error.html",
                           async_template_name = "modals/transient_error.html",
                           status_code = 503,
                           force_json = force_json,
                           context = context )


def custom_404_handler( request, exception ):
    # page_not_found_response already returns an HttpResponse with status 404.
    return page_not_found_response( request )


def home_javascript_files( request, filename ):
    return render( request, filename, {}, content_type = "text/javascript" )


class HealthView( View ):

    def get(self, request, *args, **kwargs):
        status_dict = do_healthcheck()
        response_status = 200 if status_dict['is_healthy'] else 500
        return JsonResponse( {'status': status_dict}, status = response_status )


class PrivacyAcceptView( View ):
    """Records that the visitor acknowledged the cookie-usage notice and removes the
    banner in place (an antinode replace of its wrapper)."""

    def post( self, request, *args, **kwargs ):
        PrivacyConsent.acknowledge( request )
        return antinode.response( replace_map = { 'privacy-consent-banner': '' } )


class HomeView( View ):
    """The site root (`/`): the public home/landing page, shown to *everyone* regardless of account state
    -- a marketing intro for a visitor, and (once enriched) onboarding options for an early user. Ungated:
    it needs no organization, so it stays reachable in every state -- a signed-in user can always return
    here to keep exploring (the tour, the explanation) -- with an explicit path on to their Dashboard.
    """

    def get( self, request, *args, **kwargs ):
        # The onboarding state the hero branches on is injected globally by the onboarding context
        # processor, shared with the explanation and tour surfaces, so this view stays a bare render.
        return render( request, 'pages/home.html', {} )


class ExplainView( View ):
    """The login-free "How does <SITE_NAME> work?" page: the four-step explanation of the app
    (Profile / Plans / Assumptions -> Forecast) that funnels a visitor into the example-data tour or the
    convert-to-Guest graduation. Ungated and shown in both deployment modes, so it exposes the two flags
    the template gates its cloud-only chrome on: whether authentication applies at all
    (`authentication_enabled`, false under `SUPPRESS_AUTHENTICATION` -- gates the "free, no sign-up"
    reassurance) and whether the tour can run (`tour_available`, i.e. the example org is seeded)."""

    def get( self, request, *args, **kwargs ):
        return render( request, 'pages/explain.html', {
            'authentication_enabled' : not settings.SUPPRESS_AUTHENTICATION,
            'tour_available'         : example_organization() is not None,
        } )


class DashboardView( InputGatedMixin, View ):
    """The signed-in dashboard: a known user's home within the app -- an overview of the planning features,
    led by the Financial Forecast (the one built feature), with the rest as placeholders. Input-gated
    (organization + input state); an anonymous request is redirected to `home` by the auth middleware, so
    this need not branch on account state. The forecast card's whole state is the planning layer's
    `forecast_overview`, so this view stays a thin caller."""

    def get( self, request, *args, **kwargs ):
        return render( request, 'pages/dashboard.html', {
            'forecast_overview'   : forecast_overview(
                request.organization,
                adjust_for_inflation = request.session_state.adjust_charts_for_inflation ),
            'offer_account_signin': self._offer_account_signin( request ) } )

    @staticmethod
    def _offer_account_signin( request ) -> bool:
        """Whether to offer a Guest the "already have an account?" sign-in here. It rescues the *accidental
        Guest* -- someone with an existing account who was funnelled into a throwaway one before finding the
        sign-in path. Cloud-only (self-hosting has no sign-in), Guests only (a Verified user is already
        signed in), and only when there is no plan content worth keeping -- the same signal the sign-in
        collision flow uses to adopt an existing account silently, so the offer shows exactly when signing in
        would lose nothing (a Guest who has begun real work keeps the recovery path on their account page)."""
        if settings.SUPPRESS_AUTHENTICATION or ( not request.user.is_guest ):
            return False
        return not reconciliation_service.has_plan_content( working_organization( request.user ) )


class ManifestView( View ):

    def get(self, request, *args, **kwargs):
        """Serves the PWA manifest.json."""
        return render( request, 'manifest.json', {}, content_type = "application/json" )
