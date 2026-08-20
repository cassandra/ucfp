"""The interview's Guest "save your work" reminder: the `GuestReminderMixin` decision and its
integration into `InterviewView` (the composition with flow-completeness, rendered through the
always-present swap target). Built on a real organization and a real complete profile rather than
mocked business logic, so the tests exercise `completed_profile` for real."""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from organization.models import Organization

from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.inputs.mixins import GuestReminderMixin
from ucfp.inputs.profile.repository import latest_profile, save_profile
from ucfp.planning.tests.support import forecast_profile

User = get_user_model()

# The reminder's distinctive copy, present only when the banner renders (see guest_email_banner.html).
_BANNER_COPY  = "add an email so you don't lose it"
_BANNER_TARGET = 'id="guest-email-banner"'


def _profile_flow_keys( profile ):
    return [ section.key for section in applicable_sections( profile )
             if section.form is not None and flow_of( section ) == 'profile' ]


def _complete_profile( organization ):
    """Persist `forecast_profile` as a *complete* ProfileRecord -- every profile-flow section reviewed,
    plus its filing status and housing choice -- so `completed_profile` returns it. Returns the profile."""
    profile = forecast_profile()
    record  = save_profile( organization, profile )
    record.acknowledged_sections = _profile_flow_keys( profile )
    record.save()
    return profile


def _make_incomplete( organization ):
    """Un-review the profile so it no longer counts as complete (the walk is what completes it)."""
    record = latest_profile( organization )
    record.acknowledged_sections = []
    record.save()


@override_settings( SUPPRESS_AUTHENTICATION = False )
class GuestReminderPredicateTest( TestCase ):
    """The mixin owns the whole "should the reminder show" decision. The view supplies only
    `flow_complete`; every other term (guest, complete profile, not self-hosted) is judged here."""

    def setUp( self ):
        self.mixin = GuestReminderMixin()
        self.guest = User.objects.create_guest()
        self.org   = Organization.objects.create_for_owner( self.guest, 'Household' )
        _complete_profile( self.org )

    def _request_for( self, user ):
        request = RequestFactory().get( '/inputs/interview/x/' )
        request.user         = user
        request.organization = self.org
        return request

    def test_shows_for_a_guest_with_a_complete_profile_on_a_complete_flow( self ):
        self.assertTrue( self.mixin.show_guest_reminder( self._request_for( self.guest ),
                                                         flow_complete = True ) )

    def test_hidden_while_the_current_flow_is_not_complete( self ):
        # Mid-build the banner stays clear so it never competes with an incompleteness message.
        self.assertFalse( self.mixin.show_guest_reminder( self._request_for( self.guest ),
                                                          flow_complete = False ) )

    def test_hidden_until_the_profile_is_complete( self ):
        _make_incomplete( self.org )
        self.assertFalse( self.mixin.show_guest_reminder( self._request_for( self.guest ),
                                                          flow_complete = True ) )

    def test_hidden_for_a_verified_user( self ):
        verified = User.objects.create_user( email = 'v@example.com' )
        self.assertFalse( self.mixin.show_guest_reminder( self._request_for( verified ),
                                                          flow_complete = True ) )

    @override_settings( SUPPRESS_AUTHENTICATION = True )
    def test_hidden_under_suppressed_authentication( self ):
        # Self-hosted: the data is the server's, not browser-bound, so the reminder does not apply.
        self.assertFalse( self.mixin.show_guest_reminder( self._request_for( self.guest ),
                                                          flow_complete = True ) )


@override_settings( SUPPRESS_AUTHENTICATION = False )
class InterviewBannerIntegrationTest( TestCase ):
    """End-to-end through `InterviewView`: the reminder appears in the rendered profile page only for a
    Guest whose flow is complete, and the swap-target div is always present (so an async advance can
    clear a banner shown earlier). Guards the view-level composition the predicate unit test cannot: the
    `current_flow_complete` term and the always-rendered `id` root of the swap target."""

    def _url_for_owner( self, user ):
        organization = Organization.objects.create_for_owner( user, 'Household' )
        profile      = _complete_profile( organization )
        section      = _profile_flow_keys( profile )[ 0 ]
        return organization, reverse( 'interview_section', kwargs = { 'section': section } )

    def test_guest_on_a_complete_profile_flow_sees_the_reminder( self ):
        guest = User.objects.create_guest()
        _, url = self._url_for_owner( guest )
        self.client.force_login( guest )

        response = self.client.get( url )

        self.assertContains( response, _BANNER_TARGET )   # the swap target always renders
        self.assertContains( response, _BANNER_COPY )     # ...carrying the reminder here

    def test_verified_user_sees_the_swap_target_but_not_the_reminder( self ):
        verified = User.objects.create_user( email = 'v@example.com' )
        _, url = self._url_for_owner( verified )
        self.client.force_login( verified )

        response = self.client.get( url )

        self.assertContains( response, _BANNER_TARGET )      # still present, so it can clear/appear live
        self.assertNotContains( response, _BANNER_COPY )     # ...but empty for a verified account

    def test_guest_with_an_incomplete_profile_sees_no_reminder( self ):
        guest = User.objects.create_guest()
        organization, url = self._url_for_owner( guest )
        _make_incomplete( organization )
        self.client.force_login( guest )

        response = self.client.get( url )

        self.assertContains( response, _BANNER_TARGET )
        self.assertNotContains( response, _BANNER_COPY )
