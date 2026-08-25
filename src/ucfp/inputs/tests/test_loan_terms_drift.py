"""The third copy of a loan's terms: the `LoanTermsSnapshot` a repayment records at seed time, and the
value-drift it enables. When the Profile contract terms change after a plan was established, the snapshot
no longer matches -- surfaced as drift and reconciled by reset (adopt the new contract) or keep (retain the
plan). Covers the write lifecycle (in the debt plan) and the drift/reset/keep model in `compatibility`."""
from decimal import Decimal

from django.http import QueryDict
from django.test import SimpleTestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.inputs.compatibility import (
    keep_loan_terms, loan_terms_drift, plans_reconciled_with_profile, reset_loan_terms, snapshot_of )
from ucfp.inputs.debt_plan import DebtPlanForm
from ucfp.inputs.plans.schemas import LoanRepayment, LoanTermsSnapshot, Plans
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt, LoanTerms, Profile


def _months( n : int ) -> Duration:
    return Duration( n, TimeUnit.MONTH )


def _terms( rate = 6, months = 48 ) -> LoanTerms:
    return LoanTerms( interest_rate = Rate.percent( rate ), remaining_term = _months( months ),
                      monthly_payment = Decimal( '450' ) )


def _debt( terms = None ) -> Debt:
    return Debt( handle = 'debt-1', name = 'Student loan', kind = DebtKind.STUDENT,
                 balance = Decimal( '15000' ), terms = terms )


def _repayment( rate = 6, months = 48 ) -> LoanRepayment:
    return LoanRepayment( debt_handle = 'debt-1', interest_rate = Rate.percent( rate ),
                          remaining_term = _months( months ) )


class SnapshotWriteLifecycleTests( SimpleTestCase ):
    """The debt plan records a snapshot when a repayment is first saved, preserves it across later plan
    edits (so drift is not silently accepted), and drops it when the repayment is removed."""

    def _apply( self, profile, plans, **fields ):
        data = QueryDict( mutable = True )
        data.update( fields )
        form = DebtPlanForm( data, profile = profile, plans = plans )
        assert form.is_valid(), form.errors
        _profile, plans = form.apply( profile, plans )
        return plans

    def test_a_new_repayment_records_the_current_contract_as_the_snapshot( self ):
        profile = Profile( debts = [ _debt( _terms( 6, 48 ) ) ] )
        plans   = self._apply( profile, Plans(), **{ 'rate_debt-1': '6', 'term_debt-1': '48' } )
        self.assertEqual( len( plans.loan_terms_snapshots ), 1 )
        snap = plans.loan_terms_snapshots[ 0 ]
        self.assertEqual( ( snap.debt_handle, snap.interest_rate, snap.remaining_term ),
                          ( 'debt-1', Rate.percent( 6 ), _months( 48 ) ) )

    def test_an_existing_snapshot_is_preserved_across_a_plan_edit( self ):
        # The snapshot holds the contract at seed time (5%/60); the Profile now says 6%/48 and the user
        # edits the plan. The snapshot must NOT silently refresh -- drift stays visible until reset/keep.
        profile = Profile( debts = [ _debt( _terms( 6, 48 ) ) ] )
        plans   = Plans( loan_repayments = [ _repayment( 5, 60 ) ],
                         loan_terms_snapshots = [ LoanTermsSnapshot( 'debt-1', Rate.percent( 5 ),
                                                                     _months( 60 ) ) ] )
        result  = self._apply( profile, plans, **{ 'rate_debt-1': '5', 'term_debt-1': '60',
                                                   'extra_debt-1': '100' } )
        self.assertEqual( result.loan_terms_snapshots[ 0 ].interest_rate, Rate.percent( 5 ) )   # preserved
        self.assertEqual( result.loan_terms_snapshots[ 0 ].remaining_term, _months( 60 ) )

    def test_removing_the_repayment_drops_the_snapshot( self ):
        profile = Profile( debts = [ _debt( _terms( 6, 48 ) ) ] )
        plans   = Plans( loan_repayments = [ _repayment() ],
                         loan_terms_snapshots = [ snapshot_of( 'debt-1', _terms() ) ] )
        result  = self._apply( profile, plans, **{ 'rate_debt-1': '', 'term_debt-1': '' } )
        self.assertEqual( result.loan_terms_snapshots, [] )


class LoanTermsDriftTests( SimpleTestCase ):

    def test_a_snapshot_matching_the_profile_is_not_drift( self ):
        profile = Profile( debts = [ _debt( _terms( 6, 48 ) ) ] )
        plans   = Plans( loan_terms_snapshots = [ snapshot_of( 'debt-1', _terms( 6, 48 ) ) ] )
        self.assertEqual( loan_terms_drift( profile, plans ), [] )

    def test_a_changed_profile_rate_or_term_is_drift( self ):
        profile = Profile( debts = [ _debt( _terms( 7, 48 ) ) ] )                 # contract now 7%
        plans   = Plans( loan_terms_snapshots = [ snapshot_of( 'debt-1', _terms( 6, 48 ) ) ] )
        self.assertEqual( loan_terms_drift( profile, plans ), [ 'debt-1' ] )

    def test_a_payment_only_change_is_not_drift( self ):
        # Only rate/term matter; a different stored payment (e.g. after a balance edit) is not drift.
        profile = Profile( debts = [ _debt( LoanTerms( Rate.percent( 6 ), _months( 48 ),
                                                       Decimal( '999' ) ) ) ] )
        plans   = Plans( loan_terms_snapshots = [ snapshot_of( 'debt-1', _terms( 6, 48 ) ) ] )
        self.assertEqual( loan_terms_drift( profile, plans ), [] )

    def test_a_snapshot_for_a_removed_debt_is_not_value_drift( self ):
        # The debt is gone -- that is existence drift (pruned by reconcile), not reported here.
        plans = Plans( loan_terms_snapshots = [ snapshot_of( 'debt-1', _terms() ) ] )
        self.assertEqual( loan_terms_drift( Profile(), plans ), [] )

    def test_reconcile_prunes_a_snapshot_for_a_removed_debt( self ):
        plans      = Plans( loan_terms_snapshots = [ snapshot_of( 'debt-1', _terms() ) ] )
        reconciled = plans_reconciled_with_profile( Profile(), plans )
        self.assertEqual( reconciled.loan_terms_snapshots, [] )


class ResetAndKeepTests( SimpleTestCase ):

    def _drifted_plans( self ) -> Plans:
        # Plan repayment is 5%/60 (deliberately off-contract); snapshot recorded the old 6%/48 contract.
        return Plans( loan_repayments = [ _repayment( 5, 60 ) ],
                      loan_terms_snapshots = [ LoanTermsSnapshot( 'debt-1', Rate.percent( 6 ),
                                                                  _months( 48 ) ) ] )

    def test_reset_reseeds_the_repayment_and_clears_the_drift( self ):
        profile = Profile( debts = [ _debt( _terms( 7, 36 ) ) ] )                 # contract now 7%/36
        result  = reset_loan_terms( profile, self._drifted_plans(), 'debt-1' )
        repayment = result.loan_repayments[ 0 ]
        self.assertEqual( ( repayment.interest_rate, repayment.remaining_term ),
                          ( Rate.percent( 7 ), _months( 36 ) ) )                  # re-seeded from the contract
        self.assertEqual( loan_terms_drift( profile, result ), [] )              # and the drift is gone

    def test_keep_refreshes_the_snapshot_but_leaves_the_repayment( self ):
        profile = Profile( debts = [ _debt( _terms( 7, 36 ) ) ] )
        result  = keep_loan_terms( profile, self._drifted_plans(), 'debt-1' )
        self.assertEqual( result.loan_repayments[ 0 ].interest_rate, Rate.percent( 5 ) )   # plan untouched
        self.assertEqual( result.loan_repayments[ 0 ].remaining_term, _months( 60 ) )
        self.assertEqual( loan_terms_drift( profile, result ), [] )              # drift cleared

    def test_reset_to_an_incomplete_contract_drops_the_repayment( self ):
        # The updated contract has a rate but no term -- it cannot seed a loan, so the repayment is dropped.
        profile = Profile( debts = [ _debt( LoanTerms( interest_rate = Rate.percent( 7 ) ) ) ] )
        result  = reset_loan_terms( profile, self._drifted_plans(), 'debt-1' )
        self.assertEqual( result.loan_repayments, [] )
        self.assertEqual( loan_terms_drift( profile, result ), [] )
