"""SubjectsView's partner-drop cleanup: prune the partner's own Profile facts, leave Plans as drift.

Removing a partner is a Profile edit. It prunes the departed partner's *Profile* facts -- their synced
retirement accounts and (the fix here) their income flows, pension, and Social Security entitlements --
so nothing lurks to resurrect on re-adding them, and no orphaned entitlement is left to read as an
incomplete plan once its claiming date is reconciled away. It deliberately does NOT reach into the Plans:
a plan that still references the departed partner is left as drift, reconciled on demand at the run
surface. Two regressions live here: the view once discarded the plans (passing `None` to `apply`, crashing
the paired save), and a partner drop once left the partner's income/entitlements lurking in the Profile.
"""
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.test import RequestFactory, TestCase

from common.recurrence import Duration, TimeUnit
from organization.models import Organization

from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.inputs.models import PlansRecord
from ucfp.inputs.plans.repository import latest_plans, load_plans, save_plans
from ucfp.inputs.plans.schemas import Contribution, ContributionSource, Plans
from ucfp.inputs.profile.repository import latest_profile, load_profile, save_profile
from ucfp.inputs.profile.schemas import (
    PARTNER_SUBJECT_HANDLE, PRETAX_ACCOUNT_HANDLE_PREFIX, PRIMARY_SUBJECT_HANDLE,
    AssetProfile, GovernmentPensionEntitlement, IncomeFlow, PensionEntitlement, Profile,
    SubjectProfile )
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
        data.update( { 'subject_name': 'Alice', 'subject_birthdate': '1970-01' } )
        request = self.factory.post( '/inputs/interview/subjects/edit/', data )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return request

    def test_dropping_a_partner_leaves_their_contribution_as_drift( self ):
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

        self.assertEqual( response.status_code, 200 )                          # the profile edit saves fine
        saved = load_plans( latest_plans( self.organization ) )
        # Plans are no longer pruned on a Profile edit: the contribution into the departed partner's
        # account is left as drift, reconciled on demand at the run surface.
        self.assertEqual( [ c.account_handle for c in saved.contributions ], [ _PARTNER_PRETAX ] )


class SubjectsViewPartnerFactPruningTests( TestCase ):
    """Dropping a partner prunes the partner's own Profile facts -- income flows, pension and Social
    Security entitlements -- so nothing lurks (resurrecting on re-add) and no orphaned entitlement is left
    to fail the Plans readiness check once its claiming date is reconciled away. Household income (no
    subject) and the primary's facts are untouched."""

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()

    def _post( self, *, with_partner ):
        """A Subjects auto-save POST with the primary filled and the partner present or removed."""
        data = QueryDict( mutable = True )
        data.update( { 'subject_name': 'Alice', 'subject_birthdate': '1970-01' } )
        if with_partner:
            data.update( { 'partner_name': 'Bob', 'partner_birthdate': '1972-02' } )
        request = self.factory.post( '/inputs/interview/subjects/edit/', data )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return SubjectsView().post( request )

    def _seed_household_with_partner_facts( self ):
        """A couple where the partner owns a salary flow, a pension, and a Social Security entitlement,
        alongside the primary's salary and a household (subject-less) rent flow."""
        save_profile( self.organization, Profile(
            subjects = [
                SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1970, 1, 1 ) ),
                SubjectProfile( PARTNER_SUBJECT_HANDLE, 'Bob', date( 1972, 2, 2 ) ) ],
            income_flows = [
                IncomeFlow( 'partner-salary', 'Bob Salary', PARTNER_SUBJECT_HANDLE,
                            IncomeTaxClass.WAGES, Decimal( '80000' ) ),
                IncomeFlow( 'primary-salary', 'Alice Salary', PRIMARY_SUBJECT_HANDLE,
                            IncomeTaxClass.WAGES, Decimal( '90000' ) ),
                IncomeFlow( 'rent', 'Rental income', None,
                            IncomeTaxClass.GROSS_RENTAL, Decimal( '12000' ) ) ],
            pensions = [ PensionEntitlement( PARTNER_SUBJECT_HANDLE, Decimal( '20000' ), 65 ) ],
            government_pension = [
                GovernmentPensionEntitlement( PARTNER_SUBJECT_HANDLE, Decimal( '2000' ) ) ] ) )

    def test_dropping_a_partner_prunes_their_profile_facts( self ):
        self._seed_household_with_partner_facts()
        self._post( with_partner = False )
        profile = load_profile( latest_profile( self.organization ) )
        self.assertEqual( profile.pensions, [] )                       # the partner's pension is gone ...
        self.assertEqual( profile.government_pension, [] )             # ... and their SS entitlement ...
        self.assertEqual(                                             # ... but the primary's and household income remain
            sorted( flow.handle for flow in profile.income_flows ), [ 'primary-salary', 'rent' ] )

    def test_dropped_partner_facts_do_not_resurrect_on_re_add( self ):
        self._seed_household_with_partner_facts()
        self._post( with_partner = False )   # drop: prunes the partner's facts from the Profile
        self._post( with_partner = True )    # re-add the partner as a person
        profile = load_profile( latest_profile( self.organization ) )
        self.assertEqual( len( profile.subjects ), 2 )                 # the partner is back as a person ...
        self.assertEqual( profile.government_pension, [] )             # ... but their pruned SS entitlement stays gone
        self.assertEqual( profile.pensions, [] )
        self.assertEqual(
            sorted( flow.handle for flow in profile.income_flows ), [ 'primary-salary', 'rent' ] )
