"""`profile_completion_blockers`: the "why is my profile incomplete" reasons.

Sections mark complete on visit (so the user can jump around freely), which means a fully walked profile
can still be incomplete for want of a required datum. The blockers explain that -- but only once the walk
is done, so they never pre-empt errors while the user is still entering. Today the sole hard requirement
is a person: it is what sets the filing status a run cannot run without.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from organization.models import Organization

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.inputs.interview import applicable_sections, flow_of
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.inputs.assumptions.repository import save_assumptions
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.models import AssumptionsRecord
from ucfp.inputs.plans.repository import create_plans, save_plans
from ucfp.inputs.plans.schemas import LoanRepayment, Plans, RetirementTiming
from ucfp.inputs.profile.enums import DebtKind, HousingTenure
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import (
    AssetProfile, Debt, GovernmentPensionEntitlement, IncomeFlow, Profile, SubjectProfile )
from ucfp.inputs.state import (
    assumptions_completion_blockers, assumptions_is_complete, plans_completion_blockers, plans_is_complete,
    profile_advisories, profile_completion_blockers )
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.planning.tests.support import forecast_profile


def _complete_profile_without_accounts() -> Profile:
    """A profile that can complete (a person and a housing choice) but has no funded account."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )


def _mark_all_profile_sections_reviewed( record, profile ):
    """Acknowledge every applicable profile-flow section -- the state after Next-ing through the whole
    walk."""
    record.acknowledged_sections = [ section.key for section in applicable_sections( profile )
                                     if flow_of( section ) == 'profile' and section.form is not None ]
    record.save()


class ProfileCompletionBlockersTest( TestCase ):

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Blockers' )

    def test_no_blockers_while_the_walk_is_in_progress( self ):
        # No sections acknowledged yet: still walking, so nothing is surfaced (the stepper shows progress).
        record = save_profile( self.org, Profile() )
        self.assertEqual( profile_completion_blockers( record ), [] )

    def test_walked_without_a_person_reports_the_missing_person( self ):
        profile = Profile()                                   # every section walkable, but no subject added
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertIn( 'Add at least one person.', profile_completion_blockers( record ) )

    def test_walked_without_a_housing_choice_reports_it( self ):
        # A person is present (so no person blocker), but the own/rent/neither question is unanswered.
        profile = Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE )             # home_tenure defaults to None
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertEqual( profile_completion_blockers( record ),
                          [ 'Choose whether you own or rent your home.' ] )

    def test_a_walked_profile_with_a_person_has_no_blockers( self ):
        profile = forecast_profile()                          # carries a subject (and so a filing status)
        record  = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        self.assertEqual( profile_completion_blockers( record ), [] )


def _with_income( profile ) -> Profile:
    """`profile` given a Social Security benefit, so it counts as having income (only one source needed)."""
    return replace( profile, government_pension = [ GovernmentPensionEntitlement(
        subject_handle = profile.subjects[ 0 ].handle, monthly_at_normal_age = Decimal( '2000' ) ) ] )


class ProfileAdvisoriesTest( TestCase ):
    """profile_advisories: quiet, independent FYIs for a *complete* profile -- no funded account, an owned
    home with no value, no income at all. Each is checked on its own (a profile can raise several at once),
    and all are gated on completeness, so an incomplete profile shows none."""

    def setUp( self ):
        self.org = Organization.objects.create( name = 'Advisories' )

    def _advisories( self, profile ):
        record = save_profile( self.org, profile )
        _mark_all_profile_sections_reviewed( record, profile )
        return profile_advisories( record )

    def test_no_funded_account_is_noted( self ):
        self.assertIn( 'No account balances entered yet.',
                       self._advisories( _complete_profile_without_accounts() ) )

    def test_a_funded_profile_has_no_account_note( self ):
        self.assertNotIn( 'No account balances entered yet.', self._advisories( forecast_profile() ) )

    def test_owning_without_a_home_value_is_noted( self ):
        self.assertIn( 'Home value is not set.',
                       self._advisories( replace( forecast_profile(), home_tenure = HousingTenure.OWN ) ) )

    def test_owning_with_a_home_value_has_no_home_note( self ):
        base    = forecast_profile()
        profile = replace(
            base, home_tenure = HousingTenure.OWN,
            assets = base.assets + [ AssetProfile(
                handle = 'residence', name = 'Home', asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
                opening_value = Decimal( '500000' ) ) ] )
        self.assertNotIn( 'Home value is not set.', self._advisories( profile ) )

    def test_no_income_is_noted( self ):
        self.assertIn( 'No income sources entered yet.', self._advisories( forecast_profile() ) )

    def test_income_from_only_social_security_has_no_income_note( self ):
        self.assertNotIn( 'No income sources entered yet.',
                          self._advisories( _with_income( forecast_profile() ) ) )

    def test_an_incomplete_profile_shows_no_advisory( self ):
        # Gated on completeness: a profile still missing its person shows the blocker, not FYIs.
        self.assertEqual( self._advisories( Profile() ), [] )

    def _with_rental( self, income ) -> Profile:
        profile = replace(
            _with_income( _complete_profile_without_accounts() ),   # a person + SS income, so only the rental note is at issue
            assets = [ AssetProfile( handle = 'rental', name = 'Duplex', asset_class = AssetClass.REAL_ESTATE_RENTAL,
                                     opening_value = Decimal( '300000' ) ) ] )
        if income:
            profile = replace( profile, income_flows = [ IncomeFlow(
                handle = 'rent', name = 'Rent', subject_handle = None, income_tax_class = IncomeTaxClass.GROSS_RENTAL,
                amount = Decimal( '2000' ), property_handle = 'rental' ) ] )
        return profile

    def test_a_rental_with_no_rent_income_is_noted( self ):
        notes = self._advisories( self._with_rental( income = False ) )
        self.assertTrue( any( n.startswith( 'Duplex has no rent income' ) for n in notes ) )

    def test_a_rental_with_rent_income_has_no_rental_note( self ):
        notes = self._advisories( self._with_rental( income = True ) )
        self.assertFalse( any( 'no rent income' in n for n in notes ) )


class PlansCompletionBlockersTest( TestCase ):
    """plans_completion_blockers: the "why is this plan incomplete" reasons -- today, an amortizing debt
    with no repayment plan, which the engine would otherwise silently drop (no servicing expense, no
    liability). Surfaced only once the plans flow is walked; a credit card (not amortizing) is left alone."""

    def setUp( self ):
        self.org = Organization.objects.create( name = 'PlanBlockers' )

    def _profile_with_debt( self, kind ) -> Profile:
        return Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1990, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.OWN,
            debts = [ Debt( handle = 'loan', name = 'Mortgage', kind = kind, balance = Decimal( '200000' ) ) ] )

    def _plans( self, plans ):
        record = create_plans( self.org )
        return save_plans( record, plans )

    def _walked_plans( self, profile, plans ):
        record = self._plans( plans )
        record.acknowledged_sections = [ section.key for section in applicable_sections( profile )
                                         if flow_of( section ) == 'plans' and section.form is not None ]
        record.save()
        return record

    def test_no_blockers_while_the_plans_walk_is_in_progress( self ):
        profile = self._profile_with_debt( DebtKind.MORTGAGE )
        record  = self._plans( Plans() )                       # not walked yet
        self.assertEqual( plans_completion_blockers( profile, record ), [] )

    def test_a_walked_plan_with_an_unplanned_amortizing_debt_is_blocked( self ):
        profile = self._profile_with_debt( DebtKind.MORTGAGE )
        record  = self._walked_plans( profile, Plans() )
        self.assertIn( 'Set a repayment plan for the Mortgage.', plans_completion_blockers( profile, record ) )
        self.assertFalse( plans_is_complete( profile, record ) )

    def test_a_repayment_plan_clears_the_debt_blocker( self ):
        profile = self._profile_with_debt( DebtKind.MORTGAGE )
        plans   = Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'loan', interest_rate = Rate.percent( Decimal( '6' ) ),
            remaining_term = Duration( 240, TimeUnit.MONTH ) ) ] )
        record  = self._walked_plans( profile, plans )
        self.assertEqual( plans_completion_blockers( profile, record ), [] )
        self.assertTrue( plans_is_complete( profile, record ) )

    def test_a_credit_card_debt_is_not_blocked( self ):
        profile = self._profile_with_debt( DebtKind.CREDIT_CARD )   # not amortizing -- its own plan carries it
        record  = self._walked_plans( profile, Plans() )
        self.assertEqual( plans_completion_blockers( profile, record ), [] )

    def _profile_with_benefit( self ) -> Profile:
        return Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'Robin', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER,
            government_pension = [ GovernmentPensionEntitlement(
                subject_handle = 'you', monthly_at_normal_age = Decimal( '2000' ) ) ] )

    def test_a_walked_plan_with_an_unclaimed_benefit_is_blocked( self ):
        profile = self._profile_with_benefit()
        record  = self._walked_plans( profile, Plans() )           # no claiming date placed
        self.assertIn( 'Social Security for Robin needs a claiming date.',
                       plans_completion_blockers( profile, record ) )

    def test_a_claiming_date_clears_the_benefit_blocker( self ):
        profile = self._profile_with_benefit()
        plans   = Plans( timing = [ RetirementTiming(
            subject_handle = 'you', government_pension_claiming_date = date( 2027, 1, 1 ) ) ] )
        record  = self._walked_plans( profile, plans )
        self.assertEqual( plans_completion_blockers( profile, record ), [] )


class AssumptionsCompletionBlockersTest( TestCase ):
    """assumptions_completion_blockers: the "why is this Assumptions incomplete" reasons. Today just one --
    the external factors (an economic outlook and a tax projection), which a run needs and which have no
    safe default -- surfaced only once the assumptions flow is walked."""

    def setUp( self ):
        self.org     = Organization.objects.create( name = 'AssumptionsBlockers' )
        self.profile = Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE, home_tenure = HousingTenure.NEITHER )

    def _assumptions( self, assumptions ) -> AssumptionsRecord:
        # Built directly, not minted via create_assumptions -- that pulls the externally-seeded default
        # economics, which the test DB does not carry.
        return save_assumptions( AssumptionsRecord( organization = self.org ), assumptions )

    def _walked_assumptions( self, assumptions ) -> AssumptionsRecord:
        record = self._assumptions( assumptions )
        record.acknowledged_sections = [ section.key for section in applicable_sections( self.profile )
                                         if flow_of( section ) == 'assumptions' and section.form is not None ]
        record.save()
        return record

    def test_no_blockers_while_the_assumptions_walk_is_in_progress( self ):
        record = self._assumptions( Assumptions() )            # not walked yet
        self.assertEqual( assumptions_completion_blockers( self.profile, record ), [] )

    def test_a_walked_assumptions_missing_external_factors_is_blocked( self ):
        record = self._walked_assumptions( Assumptions() )     # no economics, no tax projection
        self.assertIn( 'Set the external factors (economic outlook and tax projection).',
                       assumptions_completion_blockers( self.profile, record ) )
        self.assertFalse( assumptions_is_complete( self.profile, record ) )

    def test_external_factors_clear_the_blocker( self ):
        record = self._walked_assumptions( Assumptions(
            economics = EconomicParameters(),
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) ) )
        self.assertEqual( assumptions_completion_blockers( self.profile, record ), [] )
        self.assertTrue( assumptions_is_complete( self.profile, record ) )


class InterviewStatusRegionTest( SimpleTestCase ):
    """The `interview_status.html` region -- the badge and blockers antinode re-renders on each section
    advance. It always carries the id (the replace target), escalates from grey to danger only in the
    walked-but-blocked state, and is empty for a flow that carries no status."""

    def _render( self, context ):
        return render_to_string( 'inputs/interview/interview_status.html', context )

    def test_walked_and_blocked_shows_danger_and_the_reason( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': False,
                               'profile_blockers': [ 'Add at least one person.' ] } )
        self.assertIn( 'id="interview-status"', html )
        self.assertIn( 'badge-danger', html )
        self.assertIn( 'Add at least one person.', html )

    def test_complete_shows_success( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': True, 'profile_blockers': [] } )
        self.assertIn( 'badge-success', html )
        self.assertNotIn( 'badge-danger', html )

    def test_walk_in_progress_stays_neutral_grey( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': False, 'profile_blockers': [] } )
        self.assertIn( 'badge-secondary', html )               # neutral while walking -- not an error yet

    def test_the_assumptions_flow_shows_its_complete_state( self ):
        html = self._render( { 'flow': 'assumptions', 'assumptions_complete': True,
                               'assumptions_blockers': [] } )
        self.assertIn( 'id="interview-status"', html )
        self.assertIn( 'badge-success', html )
        self.assertNotIn( 'badge-danger', html )

    def test_the_assumptions_flow_shows_a_walked_but_blocked_set( self ):
        html = self._render( { 'flow': 'assumptions', 'assumptions_complete': False,
                               'assumptions_blockers': [ 'Set the external factors (economic outlook and tax projection).' ] } )
        self.assertIn( 'badge-danger', html )
        self.assertIn( 'Set the external factors (economic outlook and tax projection).', html )

    def test_an_unrecognized_flow_is_an_empty_region( self ):
        html = self._render( { 'flow': 'nonesuch' } )
        self.assertIn( 'id="interview-status"', html )         # present as a no-op replace target...
        self.assertNotIn( 'badge', html )                      # ...but carries no status

    def test_the_plans_flow_shows_its_complete_state( self ):
        html = self._render( { 'flow': 'plans', 'plans_complete': True, 'plans_blockers': [] } )
        self.assertIn( 'badge-success', html )
        self.assertNotIn( 'badge-danger', html )

    def test_the_plans_flow_shows_a_walked_but_blocked_debt( self ):
        html = self._render( { 'flow': 'plans', 'plans_complete': False,
                               'plans_blockers': [ 'Set a repayment plan for the Mortgage.' ] } )
        self.assertIn( 'badge-danger', html )
        self.assertIn( 'Set a repayment plan for the Mortgage.', html )

    def test_an_advisory_renders_as_an_info_alert( self ):
        html = self._render( { 'flow': 'profile', 'profile_complete': True, 'profile_blockers': [],
                               'profile_advisories': [ 'No account balances entered yet.' ] } )
        self.assertIn( 'No account balances entered yet.', html )
        self.assertIn( 'alert-info', html )                    # a noticeable info FYI...
        self.assertNotIn( 'alert-danger', html )               # ...distinct from the error blocker
