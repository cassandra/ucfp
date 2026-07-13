"""The tax run-table columns keep a run-stable identity (#tax-column-persistence).

Every forecast run mints fresh account UUIDs, so a tax column keyed by its account UUID could not be
matched back across runs and its expand/remove/reorder state would be lost. Each tax account now
displays under a per-tax-class rung (Taxes & Fees -> <tax class>), keyed by the tax-class enum, so it
renders as a single-child column carrying that stable group key. This test pins that the placement is
stamped (not silently fallen back to the engine class) and that a stored column lens survives a re-run.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.accounts.books_table import BooksColumnKey, BooksTableColumnCatalog, BooksTableDefinition
from ucfp.forecast.forecast import Forecast
from ucfp.planning.display_placement import stamp_display_placements
from ucfp.planning.materialization import ForecastFrame, materialize
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters

_TAXES_AND_FEES_KEY = 'class:EXPENSE:taxes-and-fees'


class TaxColumnPersistenceTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    def _profile( self ) -> Profile:
        # The $0 Stocks/Bonds accounts are the always-seeded sweep homes the default drawdown needs.
        return Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1955, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            assets = [
                AssetProfile( handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                              opening_value = Decimal( '900000' ), cost_basis = Decimal( '900000' ) ),
                AssetProfile( handle = 'stocks', name = 'Stocks', asset_class = AssetClass.STOCKS,
                              opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ),
                AssetProfile( handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                              opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ) ] )

    def _assumptions( self ) -> Assumptions:
        return Assumptions(
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )

    def _run_catalog( self ) -> BooksTableColumnCatalog:
        """A fresh forecast (fresh account UUIDs), stamped and turned into a column catalog."""
        frame = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        books = Forecast( materialize(
            profile = self._profile(), plans = Plans(),
            assumptions = self._assumptions(), frame = frame ) ).run().books
        stamp_display_placements( books, self._profile() )
        return books, BooksTableColumnCatalog.build( Bookkeeper( books ).chart )

    def test_tax_accounts_are_stamped_under_a_per_class_rung( self ):
        books, _catalog = self._run_catalog()
        tax_accounts = [ account for account in books.accounts
                         if ( account.expense_tax_class is not None )
                         and account.expense_tax_class.is_tax_payment ]
        self.assertTrue( tax_accounts )
        for account in tax_accounts:
            placement = account.display_placement
            self.assertIsNotNone( placement, f'{account.name} fell back (stamping failed)' )
            path = [ group.key for group in placement.path ]
            self.assertEqual( path[ 0 ], 'taxes-and-fees' )
            self.assertEqual( path[ 1 ], 'tax-' + account.expense_tax_class.name.lower() )

    def test_tax_column_layout_survives_a_re_run( self ):
        _books1, catalog1 = self._run_catalog()
        # Expand Expenses, then the Taxes & Fees surface, to bring the per-tax columns onto the frontier.
        lens = ( catalog1.default_definition()
                 .expand( catalog1, BooksColumnKey( 'type:EXPENSE' ) )
                 .expand( catalog1, BooksColumnKey( _TAXES_AND_FEES_KEY ) ) )
        stable_tax = [ token for token in lens.to_storage()[ 'columns' ]
                       if token.startswith( _TAXES_AND_FEES_KEY + '/' ) ]
        self.assertTrue( stable_tax, 'expanding Taxes & Fees yielded no per-tax columns' )

        # A brand-new run has fresh account UUIDs; the stored lens must still resolve the tax columns.
        _books2, catalog2 = self._run_catalog()
        restored = BooksTableDefinition.from_storage( lens.to_storage() ).adapt( catalog2 )
        survived = [ key.token for key in restored.column_keys
                     if key.token.startswith( _TAXES_AND_FEES_KEY + '/' ) ]
        self.assertEqual( sorted( survived ), sorted( stable_tax ) )
