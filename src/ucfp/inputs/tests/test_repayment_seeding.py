"""Seeding default loan repayments when a plan section is walked (#241).

The Debt plan and Vehicle plan sections seed a contract-following repayment for each amortizing debt they
own that lacks one, so accepting the pre-filled defaults by *walking* the section persists them -- rather
than reading as an incomplete plan ("Set a repayment plan for the ...") until each per-item editor is
opened and saved. The seeded snapshot matches the contract, so no drift is introduced, and the editor
still overrides the default.
"""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.inputs.compatibility import loan_terms_drift, seeded_repayments
from ucfp.inputs.interview import (
    DebtPlanSectionForm, VehiclePlanSectionForm, applicable_sections, flow_of )
from ucfp.inputs.plans.repository import create_plans, load_plans, save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, LoanTermsSnapshot, Plans
from ucfp.inputs.profile.enums import DebtKind, HousingTenure
from ucfp.inputs.profile.schemas import Debt, LoanTerms, Profile, SubjectProfile
from ucfp.inputs.state import plans_completion_blockers
from ucfp.jurisdiction.enums import FilingStatus


def _terms( rate = 6, months = 48 ) -> LoanTerms:
    return LoanTerms( interest_rate = Rate.percent( rate ),
                      remaining_term = Duration( months, TimeUnit.MONTH ),
                      monthly_payment = Decimal( '450' ) )


def _debt( handle = 'debt-1', kind = DebtKind.MORTGAGE, terms = None, secured = None ) -> Debt:
    return Debt( handle = handle, name = handle.title(), kind = kind, balance = Decimal( '15000' ),
                 secured_asset = secured, terms = terms if terms is not None else _terms() )


def _planned( plans ) -> set[ str ]:
    return { repayment.debt_handle for repayment in plans.loan_repayments }


def _snapshot_handles( plans ) -> list:
    return [ snapshot.debt_handle for snapshot in plans.loan_terms_snapshots ]


class SeededRepaymentsHelperTests( SimpleTestCase ):

    def test_seeds_a_default_repayment_for_an_unplanned_debt( self ):
        seeded = seeded_repayments( Plans(), [ _debt( terms = _terms( 6, 48 ) ) ] )
        self.assertEqual( _planned( seeded ), { 'debt-1' } )
        repayment = seeded.loan_repayments[ 0 ]
        self.assertEqual( ( repayment.interest_rate, repayment.remaining_term ),
                          ( Rate.percent( 6 ), Duration( 48, TimeUnit.MONTH ) ) )

    def test_seeds_several_unplanned_debts_each_with_one_snapshot( self ):
        debts  = [ _debt( 'mortgage', DebtKind.MORTGAGE, _terms( 4, 240 ) ),
                   _debt( 'student', DebtKind.STUDENT, _terms( 6, 96 ) ) ]
        seeded = seeded_repayments( Plans(), debts )
        self.assertEqual( _planned( seeded ), { 'mortgage', 'student' } )
        self.assertEqual( set( _snapshot_handles( seeded ) ), { 'mortgage', 'student' } )

    def test_the_seeded_snapshot_matches_so_there_is_no_drift( self ):
        debt   = _debt( terms = _terms( 6, 48 ) )
        seeded = seeded_repayments( Plans(), [ debt ] )
        self.assertEqual( loan_terms_drift( Profile( debts = [ debt ] ), seeded ), [] )

    def test_an_orphan_snapshot_is_replaced_by_one_fresh_snapshot_no_drift( self ):
        # A snapshot left without a repayment (an incomplete-terms reset) whose debt now has full terms:
        # seeding must not leave two snapshots for the handle, nor reuse the stale one (which would drift).
        debt   = _debt( terms = _terms( 6, 48 ) )
        stale  = LoanTermsSnapshot( debt_handle = 'debt-1', interest_rate = Rate.percent( 9 ),
                                    remaining_term = Duration( 12, TimeUnit.MONTH ) )
        seeded = seeded_repayments( Plans( loan_terms_snapshots = [ stale ] ), [ debt ] )
        self.assertEqual( _snapshot_handles( seeded ), [ 'debt-1' ] )                 # exactly one, not two
        self.assertEqual( loan_terms_drift( Profile( debts = [ debt ] ), seeded ), [] )   # fresh, no drift

    def test_an_already_planned_debt_is_left_untouched( self ):
        # Walking never overrides an existing plan (which may deliberately differ from the contract).
        existing = LoanRepayment( debt_handle = 'debt-1', interest_rate = Rate.percent( 5 ),
                                  remaining_term = Duration( 60, TimeUnit.MONTH ) )
        seeded   = seeded_repayments( Plans( loan_repayments = [ existing ] ), [ _debt() ] )
        self.assertEqual( seeded.loan_repayments, [ existing ] )

    def test_re_seeding_its_own_output_is_inert( self ):
        once  = seeded_repayments( Plans(), [ _debt( terms = _terms() ) ] )
        twice = seeded_repayments( once, [ _debt( terms = _terms() ) ] )
        self.assertEqual( twice.loan_repayments, once.loan_repayments )               # no duplicate repayment
        self.assertEqual( twice.loan_terms_snapshots, once.loan_terms_snapshots )     # no duplicate snapshot

    def test_a_debt_with_incomplete_terms_is_not_seeded( self ):
        # No resolvable rate/term -> no repayment, so it stays a real gap the blocker keeps flagging.
        debt   = _debt( terms = LoanTerms( interest_rate = Rate.percent( 6 ) ) )      # no remaining_term
        seeded = seeded_repayments( Plans(), [ debt ] )
        self.assertEqual( seeded.loan_repayments, [] )

    def test_a_balance_only_debt_with_no_terms_is_not_seeded( self ):
        debt   = Debt( handle = 'debt-1', name = 'Loan', kind = DebtKind.OTHER,
                       balance = Decimal( '5000' ), terms = None )
        seeded = seeded_repayments( Plans(), [ debt ] )
        self.assertEqual( ( seeded.loan_repayments, seeded.loan_terms_snapshots ), ( [], [] ) )


class SectionSeedOnWalkTests( SimpleTestCase ):

    def test_both_forms_seed_on_render( self ):
        self.assertTrue( DebtPlanSectionForm.seeds_on_render )
        self.assertTrue( VehiclePlanSectionForm.seeds_on_render )

    def test_the_debt_plan_section_seeds_non_auto_amortizing_debts( self ):
        profile = Profile( debts = [ _debt( 'mortgage', DebtKind.MORTGAGE ),
                                     _debt( 'card', DebtKind.CREDIT_CARD ),          # trigger, not a loan
                                     _debt( 'v1-loan', DebtKind.AUTO, secured = 'v1' ) ] )
        _profile, plans = DebtPlanSectionForm( profile = profile, plans = Plans() ).apply( profile, Plans() )
        self.assertEqual( _planned( plans ), { 'mortgage' } )        # not the card, not the auto loan

    def test_the_vehicle_plan_section_seeds_the_auto_loan( self ):
        profile = Profile( debts = [ _debt( 'v1-loan', DebtKind.AUTO, secured = 'v1' ),
                                     _debt( 'mortgage', DebtKind.MORTGAGE ) ] )
        _profile, plans = VehiclePlanSectionForm( profile = profile, plans = Plans() ).apply( profile, Plans() )
        self.assertEqual( _planned( plans ), { 'v1-loan' } )         # only the auto loan is this section's


class PlansCompletionRegressionTests( TestCase ):
    """The reported symptom, end to end against the real completion blocker: walking a plan section (its
    seed-on-render `apply`, persisted) clears "Set a repayment plan for the {debt}." without the user ever
    opening the per-item editor."""

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Seed' )

    def _profile( self, kind, handle, name ) -> Profile:
        secured = 'v1' if kind is DebtKind.AUTO else None
        return Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.OWN,
            debts = [ Debt( handle = handle, name = name, kind = kind, balance = Decimal( '20000' ),
                            secured_asset = secured, terms = _terms() ) ] )

    def _walked_record( self, profile ):
        record = save_plans( create_plans( self.org ), Plans() )
        record.acknowledged_sections = [ section.key for section in applicable_sections( profile )
                                         if flow_of( section ) == 'plans' and section.form is not None ]
        record.save()
        return record

    def _walk_section( self, form_class, profile, record ):
        _profile, seeded = form_class( profile = profile, plans = load_plans( record ) ).apply(
            profile, load_plans( record ) )
        save_plans( record, seeded )

    def test_walking_the_debt_plan_section_clears_the_blocker( self ):
        profile = self._profile( DebtKind.MORTGAGE, 'mortgage', 'Mortgage' )
        record  = self._walked_record( profile )
        self.assertIn( 'Set a repayment plan for the Mortgage.',
                       plans_completion_blockers( profile, record ) )
        self._walk_section( DebtPlanSectionForm, profile, record )
        self.assertEqual( plans_completion_blockers( profile, record ), [] )

    def test_walking_the_vehicle_plan_section_clears_the_blocker( self ):
        profile = self._profile( DebtKind.AUTO, 'v1-loan', 'My Car Loan' )
        record  = self._walked_record( profile )
        self.assertIn( 'Set a repayment plan for the My Car Loan.',
                       plans_completion_blockers( profile, record ) )
        self._walk_section( VehiclePlanSectionForm, profile, record )
        self.assertEqual( plans_completion_blockers( profile, record ), [] )
