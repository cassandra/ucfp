"""Tests for the survivor transition driven by a SubjectRemoval (a death).

One removal fans out into the tied consequences the Forecast derives: the filing-status
change (the tax law's surviving-spouse rule -- joint for the death year and two more, then
single), the subject dropping from the tax context the following year, the household-size
decrement for the subsidy, and the retitling of the decedent's accounts to the survivor (so
the survivor's age then drives RMDs). Streams stopping is left to materialization.
"""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters,
    ForecastParameters,
    SubjectRemoval,
    Subject,
    resolve_household_size,
)
from ucfp.tax.enums import TaxForecastType, TaxLawType
from ucfp.tax.law import TaxForecastProfile
from ucfp.tax.us.enums import FilingStatus
from ucfp.tax.us.filing import resolve_filing_status


def _account( reader, handle ):
    return reader.chart.account( handle )


class FilingStatusRuleTests( unittest.TestCase ):

    def test_single_base_is_unaffected( self ):
        self.assertEqual(
            resolve_filing_status( FilingStatus.SINGLE, 2030, 2035 ), FilingStatus.SINGLE )

    def test_joint_keeps_joint_through_death_year_and_two_more_then_single( self ):
        joint = FilingStatus.MARRIED_JOINT
        self.assertEqual( resolve_filing_status( joint, 2030, 2029 ), FilingStatus.MARRIED_JOINT )
        self.assertEqual( resolve_filing_status( joint, 2030, 2030 ), FilingStatus.MARRIED_JOINT )
        self.assertEqual( resolve_filing_status( joint, 2030, 2032 ), FilingStatus.MARRIED_JOINT )
        self.assertEqual( resolve_filing_status( joint, 2030, 2033 ), FilingStatus.SINGLE )

    def test_no_death_is_unaffected( self ):
        self.assertEqual(
            resolve_filing_status( FilingStatus.MARRIED_JOINT, None, 2040 ),
            FilingStatus.MARRIED_JOINT )


class HouseholdSizeResolverTests( unittest.TestCase ):

    def test_decrements_the_year_after_a_removal( self ):
        removals = [ SubjectRemoval( date( 2030, 6, 1 ), 'subject-b' ) ]
        self.assertEqual( resolve_household_size( 2, removals, 2030 ), 2 )
        self.assertEqual( resolve_household_size( 2, removals, 2031 ), 1 )


class SubjectValidationTests( unittest.TestCase ):

    def test_more_than_two_subjects_is_rejected( self ):
        with self.assertRaises( ValueError ):
            ForecastParameters(
                start_date    = date( 2026, 1, 1 ),
                end_date      = date( 2026, 12, 31 ),
                filing_status = FilingStatus.MARRIED_JOINT,
                tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
                subjects      = [
                    Subject( 'A', date( 1950, 1, 1 ), 'a' ),
                    Subject( 'B', date( 1951, 1, 1 ), 'b' ),
                    Subject( 'C', date( 1952, 1, 1 ), 'c' ) ],
            )


class SurvivorTransitionTests( unittest.TestCase ):

    def _forecast( self ):
        return Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2030, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            tax_forecast  = TaxForecastProfile( TaxLawType.US_FEDERAL, TaxForecastType.CURRENT_LAW ),
            subjects      = [
                Subject( 'A', date( 1948, 1, 1 ), 'subject-a' ),
                Subject( 'B', date( 1949, 1, 1 ), 'subject-b' ) ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ) ),
                AssetParameters(
                    'B IRA', AssetClass.PRETAX_RETIREMENT, Decimal( '100000' ), Decimal( '0' ),
                    handle = 'b-ira', owner_handle = 'subject-b' ) ],
            subject_removals = [ SubjectRemoval( date( 2027, 5, 1 ), 'subject-b' ) ],
        ) )

    def test_decedent_account_retitles_to_the_survivor( self ):
        # B dies in 2027; from 2028 B's IRA is owned by A (so A's age drives its RMD). The run
        # completing at all exercises this -- without retitling, the post-death RMD step would
        # raise on B's now-absent owner.
        reader = Bookkeeper( self._forecast().run().books )
        ira = _account( reader, 'b-ira' )
        self.assertEqual( str( ira.owner_handle ), 'subject-a' )

    def test_survivor_alone_after_death( self ):
        # after the death year the tax context carries only the survivor
        forecast = self._forecast()
        forecast.run()
        self.assertEqual(
            [ subject.name for subject in forecast._parameters.active_subjects( 2026 ) ],
            [ 'A', 'B' ] )
        self.assertEqual(
            [ subject.name for subject in forecast._parameters.active_subjects( 2028 ) ],
            [ 'A' ] )


if __name__ == '__main__':
    unittest.main()
