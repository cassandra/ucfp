from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from organization.models import Organization, OrganizationMember
from user import collision

from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
from ucfp.onboarding.reconciliation_service import sole_organization

User = get_user_model()


def _auth_user_id( client ):
    return client.session.get('_auth_user_id')


def _guest_with_org():
    guest = User.objects.create_guest()
    Organization.objects.create_for_owner( guest, 'Household' )
    return guest


def _verified_with_org( email ):
    user = User.objects.create_user( email = email )
    Organization.objects.create_for_owner( user, 'Household' )
    return user


def _give_content( user ):
    save_profile( sole_organization( user ), Profile(
        subjects = [ SubjectProfile( handle = 'subject', name = 'Alice',
                                     birthdate = date( 1980, 1, 1 ) ) ] ) )


@override_settings(SUPPRESS_AUTHENTICATION=False)
class SigninCollisionViewTest(TestCase):
    """Reconciling a signed-in Guest with the existing account they just proved they own. Cloud-only
    behavior (self-hosted has no sign-in), pinned so it does not inherit the ambient
    UCFP_SUPPRESS_AUTHENTICATION."""

    def _stash_target( self, target ):
        # Use the user-app contract to stash, as the sign-in code would.
        request = type( 'Req', (), {} )()
        request.session = self.client.session
        collision.stash_collision_target( request, target )
        request.session.save()

    def test_get_without_a_pending_collision_redirects_out(self):
        self.client.force_login( _guest_with_org() )
        response = self.client.get( reverse('signin_collision') )
        self.assertEqual( 302, response.status_code )

    def test_empty_guest_is_silently_superseded(self):
        guest = _guest_with_org()                      # no profile -> no content
        target = _verified_with_org( 'e@example.com' )
        self.client.force_login( guest )
        self._stash_target( target )

        response = self.client.get( reverse('signin_collision') )

        self.assertEqual( 302, response.status_code )
        self.assertFalse( User.objects.filter( pk = guest.pk ).exists() )   # dropped
        self.assertEqual( _auth_user_id( self.client ), str( target.pk ) )   # existing account adopted

    def test_guest_with_content_is_offered_the_choice(self):
        guest = _guest_with_org()
        _give_content( guest )
        target = _verified_with_org( 'e@example.com' )
        self.client.force_login( guest )
        self._stash_target( target )

        response = self.client.get( reverse('signin_collision') )

        self.assertEqual( 200, response.status_code )
        self.assertContains( response, 'Alice' )                            # the current plan is previewed
        self.assertTrue( User.objects.filter( pk = guest.pk ).exists() )     # nothing resolved yet

    def test_keep_current_rehomes_and_signs_in(self):
        guest = _guest_with_org()
        _give_content( guest )
        guest_org = sole_organization( guest )
        target = _verified_with_org( 'e@example.com' )
        self.client.force_login( guest )
        self._stash_target( target )

        response = self.client.post( reverse('signin_collision'), { 'choice': 'keep_current' } )

        self.assertEqual( 302, response.status_code )
        self.assertFalse( User.objects.filter( pk = guest.pk ).exists() )
        self.assertEqual( _auth_user_id( self.client ), str( target.pk ) )
        self.assertEqual( guest_org, sole_organization( target ) )           # target owns the guest's work

    def test_discard_current_signs_into_the_existing_account(self):
        guest = _guest_with_org()
        _give_content( guest )
        guest_org = sole_organization( guest )
        target = _verified_with_org( 'e@example.com' )
        target_org = sole_organization( target )
        self.client.force_login( guest )
        self._stash_target( target )

        self.client.post( reverse('signin_collision'), { 'choice': 'discard_current' } )

        self.assertEqual( _auth_user_id( self.client ), str( target.pk ) )
        self.assertEqual( target_org, sole_organization( target ) )          # existing plan kept
        self.assertEqual( 0, OrganizationMember.objects.filter( organization = guest_org ).count() )

    def test_decide_later_leaves_the_guest_untouched(self):
        guest = _guest_with_org()
        _give_content( guest )
        target = _verified_with_org( 'e@example.com' )
        self.client.force_login( guest )
        self._stash_target( target )

        self.client.post( reverse('signin_collision'), { 'choice': 'decide_later' } )

        self.assertTrue( User.objects.filter( pk = guest.pk ).exists() )     # still a Guest
        self.assertEqual( _auth_user_id( self.client ), str( guest.pk ) )     # not switched


@override_settings(SUPPRESS_AUTHENTICATION=True)
class SigninCollisionDisabledSelfHostedTest(TestCase):
    """The collision reconcile is part of the sign-in flow, so it is rejected with an explanatory 400
    under self-hosted (SUPPRESS_AUTHENTICATION) -- a single-user deployment never has two accounts to
    reconcile."""

    def test_collision_is_rejected_self_hosted( self ):
        response = self.client.get( reverse('signin_collision') )

        self.assertEqual( 400, response.status_code )
        self.assertContains( response, 'self-hosted', status_code = 400 )
