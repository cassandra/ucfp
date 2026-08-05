"""SubjectsView's partner-drop plan pruning.

Removing a partner drops their synced retirement accounts, so any plan contribution into one becomes
dangling. The Subjects pane must prune those references and persist the pruned plans alongside the
profile. The regression: the view discarded the plans (saving only the profile, passing `None` to
`apply`), which crashed the prune with `'NoneType' object has no attribute 'contributions'` -- and,
absent the crash, would have left the contribution orphaned and unsaved.
"""
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.test import RequestFactory, TestCase

from common.recurrence import Duration, TimeUnit
from organization.models import Organization

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.models import PlansRecord
from ucfp.inputs.plans.repository import latest_plans, load_plans, save_plans
from ucfp.inputs.plans.schemas import Contribution, ContributionSource, Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import (
    PARTNER_SUBJECT_HANDLE, PRETAX_ACCOUNT_HANDLE_PREFIX, PRIMARY_SUBJECT_HANDLE,
    AssetProfile, Profile, SubjectProfile )
from ucfp.inputs.views import SubjectsView
from ucfp.session_state import SessionState

_PARTNER_PRETAX = f'{PRETAX_ACCOUNT_HANDLE_PREFIX}{PARTNER_SUBJECT_HANDLE}'


class SubjectsViewPartnerDropTests( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()

    def _drop_partner_request( self ):
        """A Subjects auto-save POST with only the primary filled -- i.e. the partner removed."""
        data = QueryDict( mutable = True )
        data.update( { 'subject_name': 'Alice', 'subject_birthdate': '1970-01-01' } )
        request = self.factory.post( '/inputs/interview/subjects/edit/', data )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return request

    def test_dropping_a_partner_prunes_their_contribution_and_saves( self ):
        # A household with a partner, the partner's pre-tax account, and a plan contribution into it.
        save_profile( self.organization, Profile(
            subjects = [
                SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1970, 1, 1 ) ),
                SubjectProfile( PARTNER_SUBJECT_HANDLE, 'Bob', date( 1972, 2, 2 ) ) ],
            assets = [ AssetProfile(
                handle = _PARTNER_PRETAX, name = 'Bob Pre-tax', asset_class = AssetClass.PRETAX_RETIREMENT,
                opening_value = Decimal( '0' ), owner_handle = PARTNER_SUBJECT_HANDLE ) ] ) )
        save_plans(
            PlansRecord( organization = self.organization, label = 'Plans' ),
            Plans( contributions = [ Contribution(
                handle = 'contribution-1', account_handle = _PARTNER_PRETAX, amount = Decimal( '100' ),
                source = ContributionSource.PERSONAL, interval = Duration( 1, TimeUnit.YEAR ) ) ] ) )

        response = SubjectsView().post( self._drop_partner_request() )

        self.assertEqual( response.status_code, 200 )                          # no crash on the prune
        saved = load_plans( latest_plans( self.organization ) )
        self.assertEqual( saved.contributions, [] )                            # dangling contribution pruned
