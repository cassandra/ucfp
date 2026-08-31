"""End-to-end Social Security through materialization: a couple's Profile entitlements + Plans claiming
timing materialize into engine SocialSecurityEntitlement facts, and the engine computes the couple-aware
benefit per interval (own + the lower earner's spousal top-up) into per-subject SS accounts.

This covers the migration seam -- couple SS moved out of materialization into the engine -- from the
Profile all the way to the booked income.
"""
import unittest
from datetime import date
from decimal import Decimal

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.schemas import Plans, RetirementTiming
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import (
    AssetProfile, GovernmentPensionEntitlement, Profile, SubjectProfile )
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.planning.materialization import ForecastFrame, materialize


def _couple_profile():
    sweep = [
        AssetProfile( 'cash', 'Cash', AssetClass.CASH, Decimal( '500000' ), Decimal( '500000' ) ),
        AssetProfile( 'stocks', 'Stocks', AssetClass.STOCKS, Decimal( '0' ), Decimal( '0' ) ),
        AssetProfile( 'bonds', 'Bonds', AssetClass.BONDS, Decimal( '0' ), Decimal( '0' ) ) ]
    return Profile(
        subjects = [ SubjectProfile( 'subject', 'You', date( 1960, 1, 1 ) ),
                     SubjectProfile( 'partner', 'Partner', date( 1960, 1, 1 ) ) ],
        filing_status = FilingStatus.MARRIED_JOINT,
        home_tenure = HousingTenure.NEITHER,
        assets = sweep,
        government_pension = [                              # subject is the higher earner (PIA 3000)
            GovernmentPensionEntitlement( 'subject', Decimal( '3000' ) ),
            GovernmentPensionEntitlement( 'partner', Decimal( '1000' ) ) ] )


class SocialSecurityMaterializationTest( unittest.TestCase ):

    def _run( self ):
        plans = Plans( timing = [                           # both claim at FRA (67, born 1960) in 2027
            RetirementTiming( 'subject', government_pension_claiming_date = date( 2027, 1, 1 ) ),
            RetirementTiming( 'partner', government_pension_claiming_date = date( 2027, 1, 1 ) ) ] )
        assumptions = Assumptions(
            economics = EconomicParameters(),               # no COLA, to isolate the benefit amounts
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )
        frame = ForecastFrame( date( 2026, 1, 1 ), date( 2029, 12, 31 ), Duration( 1, TimeUnit.YEAR ) )
        return Forecast( materialize( _couple_profile(), plans, assumptions, frame ) ).run()

    def test_materialized_couple_books_own_and_spousal_per_subject( self ):
        reader = Bookkeeper( self._run().books )

        def ss_year( handle, year ):
            account = reader.chart.income_account( IncomeTaxClass.SOCIAL_SECURITY, owner_handle = handle )
            return ( reader.ledger.natural_balance( account, through = date( year, 12, 31 ) )
                     - reader.ledger.natural_balance( account, through = date( year - 1, 12, 31 ) ) )

        self.assertEqual( ss_year( 'subject', 2026 ), Decimal( '0' ) )        # before the 2027 claim
        self.assertEqual( ss_year( 'subject', 2028 ), Decimal( '36000' ) )    # higher earner: own, 3000*12
        # lower earner: own 12000 + spousal excess (1500-1000)*12 = 6000, both collecting from 2027.
        self.assertEqual( ss_year( 'partner', 2028 ), Decimal( '18000' ) )


if __name__ == '__main__':
    unittest.main()
