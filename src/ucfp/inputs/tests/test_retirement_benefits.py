"""The Retirement benefits pane: per-person Social Security and pension amounts round-trip, and the split
from Incomes is clean in both directions -- this pane writes only the entitlement facts, and the Incomes
pane leaves those entitlements alone.
"""
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from ucfp.accounts.enums import IncomeTaxClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.income import IncomeTableForm
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import (
    GovernmentPensionEntitlement, IncomeFlow, PensionEntitlement, Profile, SubjectProfile )
from ucfp.inputs.retirement_benefits import RetirementBenefitsForm
from ucfp.inputs.views import RetirementBenefitsView


def _profile( **kwargs ) -> Profile:
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        **kwargs )


class RetirementBenefitsPaneTest( SimpleTestCase ):

    def test_the_pane_carries_the_view_swap_target_id( self ):
        html = render_to_string(
            RetirementBenefitsView.template,
            { RetirementBenefitsView.context_name: RetirementBenefitsForm( profile = _profile() ),
              'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertIn( f'id="{RetirementBenefitsView.target}"', html )   # else a re-render can't land


class RetirementBenefitsApplyTests( SimpleTestCase ):

    @staticmethod
    def _post( ss = '', pension = '' ) -> QueryDict:
        data = QueryDict( mutable = True )
        data[ 's0_ssamt' ]  = ss
        data[ 's0_penamt' ] = pension
        return data

    def test_the_benefits_round_trip_into_entitlement_facts( self ):
        profile = _profile()
        form = RetirementBenefitsForm( self._post( ss = '2,900', pension = '30,000' ), profile = profile )
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        self.assertEqual( result.government_pension[ 0 ].subject_handle, 'you' )
        self.assertEqual( result.government_pension[ 0 ].monthly_at_normal_age, Decimal( '2900' ) )
        self.assertEqual( result.pensions[ 0 ].base_annual_amount, Decimal( '30000' ) )

    def test_a_blank_benefit_is_not_recorded( self ):
        profile = _profile()
        form = RetirementBenefitsForm( self._post( ss = '2,900' ), profile = profile )   # pension left blank
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        self.assertEqual( len( result.government_pension ), 1 )
        self.assertEqual( len( result.pensions ), 0 )

    def test_it_leaves_income_flows_untouched( self ):
        flow = IncomeFlow( handle = 'income-1', name = 'Salary', subject_handle = 'you',
                           income_tax_class = IncomeTaxClass.WAGES, amount = Decimal( '90000' ) )
        profile = _profile( income_flows = [ flow ] )
        form = RetirementBenefitsForm( self._post( ss = '2,900' ), profile = profile )
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        self.assertEqual( result.income_flows, [ flow ] )    # the Incomes section owns these


class IncomeLeavesBenefitsAloneTest( SimpleTestCase ):
    """The other half of the split: the Incomes pane rewrites income flows but must not clobber the
    per-person entitlements the Retirement benefits pane owns."""

    def test_income_apply_preserves_entitlements( self ):
        profile = _profile(
            government_pension = [ GovernmentPensionEntitlement(
                subject_handle = 'you', monthly_at_normal_age = Decimal( '2900' ) ) ],
            pensions = [ PensionEntitlement(
                subject_handle = 'you', base_annual_amount = Decimal( '30000' ), normal_start_age = 65 ) ] )
        data = QueryDict( mutable = True )
        data.setlist( 'income_name', [ 'Salary' ] )
        data.setlist( 'income_subject', [ 'you' ] )
        data.setlist( 'income_amount', [ '90,000' ] )
        data.setlist( 'income_handle', [ '' ] )
        form = IncomeTableForm( data, profile = profile )
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        self.assertEqual( result.government_pension, profile.government_pension )   # untouched
        self.assertEqual( result.pensions, profile.pensions )
