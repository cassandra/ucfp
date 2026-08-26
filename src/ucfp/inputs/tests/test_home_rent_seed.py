"""seeded_home_rent: the Plans rented-home rent expense is seeded from the Profile `home_monthly_rent`
fact once (recording a snapshot for drift); owners, a blank fact, and an already-seeded plan are no-ops.
Mirrors a loan repayment's `preserved_snapshot` -- seed once on the Plans side, then let drift surface a
later Profile edit.
"""
from dataclasses import replace
from decimal import Decimal

from django.test import TestCase

from ucfp.inputs.compatibility import home_rent_drift, keep_home_rent, reset_home_rent
from ucfp.inputs.interview import HomeExpensesSectionForm
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.property_expenses import (
    RENT_EXPENSE_HANDLE, merged_property_expenses, seeded_home_rent )
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets


def _renter( rent = '1800' ) -> Profile:
    return Profile( home_tenure = HousingTenure.RENT, home_monthly_rent = Decimal( rent ) )


def _plans_for( profile ) -> Plans:
    return Plans( property_expenses = merged_property_expenses( profile, Plans() ) )


def _rent_amount( plans ):
    row = next( e for e in plans.property_expenses if e.handle == RENT_EXPENSE_HANDLE )
    return row.default_amount


class SeedHomeRentTests( TestCase ):
    """`merged_property_expenses` reads the seeded parameter-set catalog, so this needs a seeded DB."""

    @classmethod
    def setUpTestData( cls ):
        seed_default_parameter_sets()

    def test_first_seed_sets_the_rent_and_the_snapshot( self ):
        profile = _renter( '1800' )
        seeded  = seeded_home_rent( profile, _plans_for( profile ) )
        self.assertEqual( seeded.home_rent_snapshot, Decimal( '1800' ) )
        self.assertEqual( _rent_amount( seeded ), Decimal( '1800' ) )     # the rent row's shared default

    def test_an_already_seeded_plan_is_preserved( self ):
        # Snapshot present -> no re-seed, even though the fact now differs (that divergence is drift).
        profile = _renter( '2500' )
        plans   = replace( _plans_for( profile ), home_rent_snapshot = Decimal( '1800' ) )
        before  = _rent_amount( plans )
        result  = seeded_home_rent( profile, plans )
        self.assertEqual( result.home_rent_snapshot, Decimal( '1800' ) )  # unchanged
        self.assertEqual( _rent_amount( result ), before )                # unchanged

    def test_an_owner_is_a_no_op( self ):
        result = seeded_home_rent( Profile( home_tenure = HousingTenure.OWN ), Plans() )
        self.assertIsNone( result.home_rent_snapshot )

    def test_a_blank_rent_is_a_no_op( self ):
        profile = Profile( home_tenure = HousingTenure.RENT )             # renting, no rent entered
        result  = seeded_home_rent( profile, _plans_for( profile ) )
        self.assertIsNone( result.home_rent_snapshot )

    def test_the_home_expenses_section_seeds_on_apply( self ):
        # The real seeds_on_render path: presenting Home Expenses seeds a fresh Plans from the Profile fact.
        profile = _renter( '1800' )
        _p, plans = HomeExpensesSectionForm( profile = profile, plans = Plans() ).apply( profile, Plans() )
        self.assertEqual( plans.home_rent_snapshot, Decimal( '1800' ) )
        self.assertEqual( _rent_amount( plans ), Decimal( '1800' ) )


class HomeRentDriftTests( TestCase ):
    """The Profile-rent-vs-seeded drift and its two reconciles (update / keep)."""

    @classmethod
    def setUpTestData( cls ):
        seed_default_parameter_sets()

    def _seeded( self, rent = '1800' ):
        profile = _renter( rent )
        return profile, seeded_home_rent( profile, _plans_for( profile ) )

    def test_no_drift_when_the_fact_is_in_step( self ):
        profile, plans = self._seeded()
        self.assertFalse( home_rent_drift( profile, plans ) )

    def test_drift_fires_when_the_profile_rent_changes( self ):
        _profile, plans = self._seeded( '1800' )
        changed = _renter( '2500' )
        self.assertTrue( home_rent_drift( changed, plans ) )

    def test_switching_to_own_does_not_read_as_rent_drift( self ):
        _profile, plans = self._seeded( '1800' )   # snapshot 1800 lingers
        owner = Profile( home_tenure = HousingTenure.OWN )   # no longer renting, rent fact cleared
        self.assertFalse( home_rent_drift( owner, plans ) )

    def test_reset_adopts_the_fact_and_clears_the_drift( self ):
        _profile, plans = self._seeded( '1800' )
        changed = _renter( '2500' )
        reset   = reset_home_rent( changed, plans )
        self.assertEqual( reset.home_rent_snapshot, Decimal( '2500' ) )
        self.assertEqual( _rent_amount( reset ), Decimal( '2500' ) )   # plan rent updated to the fact
        self.assertFalse( home_rent_drift( changed, reset ) )

    def test_keep_refreshes_the_snapshot_but_leaves_the_plan( self ):
        _profile, plans = self._seeded( '1800' )
        changed = _renter( '2500' )
        kept    = keep_home_rent( changed, plans )
        self.assertEqual( kept.home_rent_snapshot, Decimal( '2500' ) )  # snapshot follows the fact
        self.assertEqual( _rent_amount( kept ), Decimal( '1800' ) )     # plan rent unchanged
        self.assertFalse( home_rent_drift( changed, kept ) )
