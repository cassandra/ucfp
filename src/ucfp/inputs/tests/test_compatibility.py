"""The Plans <-> Profile compatibility check: every Plans reference must resolve against the Profile."""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.schemas import AssetProfile, LoanProfile, Profile, SubjectProfile
from ucfp.inputs.plans.schemas import LoanPrepayment, Plans, RetirementTiming
from ucfp.inputs.compatibility import (
    PlansIncompatibleError, assert_compatible, compatibility_issues )


def _profile() -> Profile:
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        assets = [ AssetProfile( handle = 'savings', name = 'Savings', asset_class = AssetClass.CASH,
                                 opening_value = Decimal( '1000' ) ) ],
        loans = [ LoanProfile(
            handle = 'mortgage', name = 'Mortgage', origination_date = date( 2010, 1, 1 ),
            original_amount = Decimal( '300000' ), interest_rate = Rate( Decimal( '0.04' ) ),
            original_term = Duration( 30, TimeUnit.YEAR ) ) ] )


class CompatibilityTest( SimpleTestCase ):

    def test_resolving_references_are_compatible( self ):
        plans = Plans(
            timing = [ RetirementTiming( subject_handle = 'you' ) ],
            prepayments = [ LoanPrepayment( loan_handle = 'mortgage',
                                            annual_amount = Decimal( '6000' ) ) ] )
        self.assertEqual( compatibility_issues( _profile(), plans ), [] )
        assert_compatible( _profile(), plans )   # does not raise

    def test_dangling_references_are_reported_and_raise( self ):
        plans = Plans(
            timing = [ RetirementTiming( subject_handle = 'ghost' ) ],
            prepayments = [ LoanPrepayment( loan_handle = 'sold-loan',
                                            annual_amount = Decimal( '6000' ) ) ] )
        issues = compatibility_issues( _profile(), plans )
        self.assertEqual( len( issues ), 2 )
        with self.assertRaises( PlansIncompatibleError ):
            assert_compatible( _profile(), plans )
