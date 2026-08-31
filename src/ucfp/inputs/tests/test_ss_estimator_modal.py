"""The Social Security FRA-benefit calculator: the wage attribution that seeds it, and the modal view
that renders the estimate and recomputes it as the income is adjusted.

The estimate itself is the jurisdiction facade's (tested in `jurisdiction`); here we cover the input-layer
glue -- which wages feed the estimate, and that the modal seeds and recomputes through the facade.
"""
import json
import re
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase, TestCase

from organization.models import Organization

from ucfp.accounts.enums import IncomeTaxClass
from ucfp.inputs.profile.repository import latest_profile, load_profile, save_profile
from ucfp.inputs.profile.schemas import (
    PARTNER_SUBJECT_HANDLE, PRIMARY_SUBJECT_HANDLE, GovernmentPensionEntitlement, IncomeFlow, Profile,
    SubjectProfile )
from ucfp.inputs.retirement_benefits import subject_wage_total
from ucfp.inputs.views import SocialSecurityBenefitApplyView, SocialSecurityEstimatorModalView
from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.session_state import SessionState


def _wages( handle, amount, name = 'Salary' ) -> IncomeFlow:
    return IncomeFlow(
        handle = f'income-{handle}', name = name, subject_handle = handle,
        income_tax_class = IncomeTaxClass.WAGES, amount = Decimal( amount ) )


def _input_value( html, field_name ):
    """The `value` attribute of the named input in a rendered fragment, parsed back to a Decimal so the
    assertion is independent of money formatting."""
    match = re.search( rf'name="{field_name}"[^>]*\bvalue="([^"]*)"', html ) \
        or re.search( rf'\bvalue="([^"]*)"[^>]*name="{field_name}"', html )
    return Decimal( match.group( 1 ) ) if match and match.group( 1 ) else None


class SubjectWageTotalTests( SimpleTestCase ):

    _PROFILE = Profile( income_flows = [
        _wages( PRIMARY_SUBJECT_HANDLE, '60000' ),
        _wages( PRIMARY_SUBJECT_HANDLE, '20000', name = 'Consulting' ),
        _wages( PARTNER_SUBJECT_HANDLE, '90000' ),
        IncomeFlow( handle = 'rent', name = 'Rent', subject_handle = None,
                    income_tax_class = IncomeTaxClass.GROSS_RENTAL, amount = Decimal( '30000' ) ),
        IncomeFlow( handle = 'other', name = 'Other', subject_handle = None,
                    income_tax_class = IncomeTaxClass.ORDINARY, amount = Decimal( '15000' ) ) ] )

    def test_it_sums_a_subjects_own_wage_flows( self ):
        self.assertEqual( subject_wage_total( self._PROFILE, PRIMARY_SUBJECT_HANDLE ), Decimal( '80000' ) )

    def test_it_excludes_other_subjects_wages( self ):
        self.assertEqual( subject_wage_total( self._PROFILE, PARTNER_SUBJECT_HANDLE ), Decimal( '90000' ) )

    def test_it_excludes_household_income( self ):
        # neither the rental nor the other (ORDINARY) household income is a person's covered wage.
        only_household = Profile( income_flows = self._PROFILE.income_flows[ 3: ] )
        self.assertEqual( subject_wage_total( only_household, PRIMARY_SUBJECT_HANDLE ), Decimal( '0' ) )

    def test_no_wages_is_zero( self ):
        self.assertEqual( subject_wage_total( Profile(), PRIMARY_SUBJECT_HANDLE ), Decimal( '0' ) )


class EstimatorModalViewTests( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()
        save_profile( self.organization, Profile(
            subjects = [ SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1965, 1, 1 ) ) ],
            income_flows = [ _wages( PRIMARY_SUBJECT_HANDLE, '80000' ) ] ) )
        self._estimator = GovernmentPension( JurisdictionType.US_FEDERAL )

    def _request( self, method, data = None ):
        request = getattr( self.factory, method )(
            '/x/', data, HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return request

    def test_get_seeds_income_from_wages_and_the_estimated_benefit( self ):
        response = SocialSecurityEstimatorModalView().get(
            self._request( 'get' ), handle = PRIMARY_SUBJECT_HANDLE )
        html = json.loads( response.content )[ 'modal' ]    # the modal HTML rides in a JSON envelope
        self.assertIn( 'Alice', html )
        self.assertEqual( _input_value( html, 'income' ), Decimal( '80000' ) )
        self.assertEqual(
            _input_value( html, 'fra_benefit' ), self._estimator.estimate_entitlement( Decimal( '80000' ) ) )

    def test_post_recomputes_the_benefit_for_the_adjusted_income( self ):
        data = QueryDict( mutable = True )
        data[ 'income' ] = '120,000'
        response = SocialSecurityEstimatorModalView().post(
            self._request( 'post', data ), handle = PRIMARY_SUBJECT_HANDLE )
        fragment = json.loads( response.content )[ 'replace' ][ 'ss-estimator-fra' ]
        self.assertEqual(
            _input_value( fragment, 'fra_benefit' ),
            self._estimator.estimate_entitlement( Decimal( '120000' ) ) )

    def test_a_larger_income_estimates_a_larger_benefit( self ):
        def benefit_for( income ):
            data = QueryDict( mutable = True )
            data[ 'income' ] = income
            response = SocialSecurityEstimatorModalView().post(
                self._request( 'post', data ), handle = PRIMARY_SUBJECT_HANDLE )
            fragment = json.loads( response.content )[ 'replace' ][ 'ss-estimator-fra' ]
            return _input_value( fragment, 'fra_benefit' )
        self.assertLess( benefit_for( '40000' ), benefit_for( '150000' ) )

    def test_an_unknown_subject_is_not_found( self ):
        from django.http import Http404
        with self.assertRaises( Http404 ):
            SocialSecurityEstimatorModalView().get( self._request( 'get' ), handle = 'ghost' )


class BenefitApplyViewTests( TestCase ):
    """Confirm writes the subject's Social Security entitlement fact and re-renders the benefits table."""

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        self.factory      = RequestFactory()
        save_profile( self.organization, Profile(
            subjects = [ SubjectProfile( PRIMARY_SUBJECT_HANDLE, 'Alice', date( 1965, 1, 1 ) ),
                         SubjectProfile( PARTNER_SUBJECT_HANDLE, 'Bob', date( 1963, 1, 1 ) ) ],
            government_pension = [
                GovernmentPensionEntitlement( PARTNER_SUBJECT_HANDLE, Decimal( '2000' ) ) ] ) )

    def _confirm( self, handle, fra_benefit ):
        data = QueryDict( mutable = True )
        data[ 'fra_benefit' ] = fra_benefit
        request = self.factory.post( '/x/', data, HTTP_X_REQUESTED_WITH = 'XMLHttpRequest' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return SocialSecurityBenefitApplyView().post( request, handle = handle )

    def _saved_benefits( self ):
        profile = load_profile( latest_profile( self.organization ) )
        return { entry.subject_handle: entry.monthly_at_normal_age
                 for entry in profile.government_pension }

    def test_confirm_writes_the_subjects_entitlement_and_returns_the_table( self ):
        response = self._confirm( PRIMARY_SUBJECT_HANDLE, '2,900' )
        self.assertEqual( self._saved_benefits()[ PRIMARY_SUBJECT_HANDLE ], Decimal( '2900' ) )
        self.assertIn( 'retirement-benefits-table', json.loads( response.content )[ 'replace' ] )

    def test_it_leaves_other_subjects_entitlements_untouched( self ):
        self._confirm( PRIMARY_SUBJECT_HANDLE, '2,900' )
        self.assertEqual( self._saved_benefits()[ PARTNER_SUBJECT_HANDLE ], Decimal( '2000' ) )

    def test_a_blank_confirm_clears_the_entitlement( self ):
        self._confirm( PARTNER_SUBJECT_HANDLE, '' )
        self.assertNotIn( PARTNER_SUBJECT_HANDLE, self._saved_benefits() )

    def test_an_unknown_subject_is_not_found( self ):
        from django.http import Http404
        with self.assertRaises( Http404 ):
            self._confirm( 'ghost', '2900' )
