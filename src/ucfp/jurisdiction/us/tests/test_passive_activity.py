"""The passive-activity-loss release on a full rental disposition (#115).

A rental's losses suspend while held (a loss beyond the active-participation allowance is carried
forward); a full disposition of the aggregate activity frees the whole suspended balance in the sale
year, while a partial disposition (some rentals still held) does not. Exercises
`_passive_activity_result` directly with a controlled context, isolating the release from the
surrounding return."""
import unittest
from datetime import date
from decimal import Decimal

from ucfp.accounts.books import Account
from ucfp.accounts.enums import AccountType, AssetClass
from ucfp.jurisdiction.context import TaxContext
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.property import PropertyDisposition, TaxProperty
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026

_D = Decimal


_ASSET_ROOT = Account( name = 'Assets', account_type = AccountType.ASSET )


def _rental( disposed ):
    holding     = Account(
        name = 'Rental', parent = _ASSET_ROOT, asset_class = AssetClass.REAL_ESTATE_RENTAL )
    disposition = PropertyDisposition( sale_date = date( 2026, 6, 1 ) ) if disposed else None
    return TaxProperty(
        holding = holding, acquisition_date = date( 2010, 1, 1 ), disposition = disposition )


def _context( *rentals ):
    return TaxContext( filing_status = FilingStatus.SINGLE, properties = tuple( rentals ) )


class PassiveLossReleaseTests( unittest.TestCase ):

    def setUp( self ):
        self.engine = USFederalTaxEngine( federal_2026() )

    def _result( self, net_rental, prior_suspended, context ):
        # A phase-out MAGI well above the band -> zero active-participation allowance, so a loss on a
        # held rental is fully suspended -- isolating what the disposition then releases.
        return self.engine._passive_activity_result(
            _D( net_rental ), _D( '300000' ), _D( prior_suspended ), context )

    def test_held_rental_suspends_the_loss_beyond_the_allowance( self ):
        result = self._result( '-5000', '20000', _context( _rental( disposed = False ) ) )
        self.assertEqual( result.deductible, _D( '0' ) )       # nothing allowed at a zero allowance
        self.assertEqual( result.suspended, _D( '25000' ) )    # 5k current + 20k prior, all suspended

    def test_full_disposition_releases_all_suspended_losses( self ):
        result = self._result( '-5000', '20000', _context( _rental( disposed = True ) ) )
        self.assertEqual( result.deductible, _D( '-25000' ) )  # the whole loss deducts against income
        self.assertEqual( result.suspended, _D( '0' ) )        # nothing carries forward

    def test_partial_disposition_does_not_release( self ):
        # One rental sold, another still held: the aggregate activity is not fully wound down.
        context = _context( _rental( disposed = True ), _rental( disposed = False ) )
        self.assertEqual( self._result( '-5000', '20000', context ).suspended, _D( '25000' ) )

    def test_disposing_every_rental_releases( self ):
        context = _context( _rental( disposed = True ), _rental( disposed = True ) )
        self.assertEqual( self._result( '-5000', '20000', context ).suspended, _D( '0' ) )


if __name__ == '__main__':
    unittest.main()
