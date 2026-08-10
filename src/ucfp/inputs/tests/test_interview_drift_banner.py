"""InterviewView surfaces a Plans-flow drift banner: the current Plans' stale Profile references,
shown where the user meets their effect (e.g. the Debt plan after deleting the debt), with the one-click
reconcile. Off the Plans flow there is no banner -- only Plans reference the Profile.
"""
from decimal import Decimal

from django.test import RequestFactory, TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.models import PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.views import InterviewView
from ucfp.session_state import SessionState


class InterviewDriftBannerTests( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Org' )
        save_profile( self.org, Profile() )                    # a profile with no debts
        self.plans = PlansRecord( organization = self.org, label = 'P' )
        save_plans( self.plans, Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'gone', interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] ) )

    def _request( self ):
        request = RequestFactory().get( '/inputs/interview/x/' )
        request.organization  = self.org
        request.session_state = SessionState( current_plans_uuid = str( self.plans.uuid ) )
        return request

    def test_the_plans_flow_surfaces_the_current_plans_drift( self ):
        drift = InterviewView._plans_drift( self._request(), 'plans' )
        self.assertIsNotNone( drift )
        self.assertEqual( drift[ 'references' ], [ 'a repayment plan for an unknown debt "gone"' ] )
        self.assertEqual( drift[ 'fix_url' ], f'/inputs/plans/{self.plans.uuid}/reconcile/' )

    def test_other_flows_show_no_banner( self ):
        self.assertIsNone( InterviewView._plans_drift( self._request(), 'profile' ) )
        self.assertIsNone( InterviewView._plans_drift( self._request(), 'assumptions' ) )
