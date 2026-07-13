"""Engine-created run-table columns keep a run-stable identity (#tax/income-column-persistence).

Every forecast run mints fresh account UUIDs, so a column keyed by its account UUID could not be
matched back across runs and its expand/remove/reorder state would be lost. Two families of columns
are engine-created and so lack an input handle to key on:

  - Tax accounts, under a per-tax-class rung below the Taxes & Fees surface.
  - Income accounts, under a per-tax-class rung below their income source (and owning subject).

Each rung holds exactly one account, so the account renders as a single-child column carrying the
rung's stable group key. These tests pin that the placements are stamped (not silently fallen back to
the engine class) and that a stored column lens survives a fresh run's new UUIDs.
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

_TAXES_AND_FEES_KEY    = 'class:EXPENSE:taxes-and-fees'
_INVESTMENT_INCOME_KEY = 'class:REVENUE:investment'


class EngineColumnPersistenceTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )

    def _profile( self ) -> Profile:
        # Funded Dividend Stocks and Bonds drive several investment-income classes (dividends, gains,
        # interest); the $0 Stocks account is the always-seeded sweep home the default drawdown needs.
        return Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1955, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            assets = [
                AssetProfile( handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                              opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) ),
                AssetProfile( handle = 'divs', name = 'Dividend Stocks',
                              asset_class = AssetClass.DIVIDEND_STOCKS,
                              opening_value = Decimal( '300000' ), cost_basis = Decimal( '150000' ) ),
                AssetProfile( handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                              opening_value = Decimal( '300000' ), cost_basis = Decimal( '300000' ) ),
                AssetProfile( handle = 'stocks', name = 'Stocks', asset_class = AssetClass.STOCKS,
                              opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ) ] )

    def _assumptions( self ) -> Assumptions:
        return Assumptions(
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )

    def _run_catalog( self ):
        """A fresh forecast (fresh account UUIDs), stamped and turned into a column catalog."""
        frame = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        books = Forecast( materialize(
            profile = self._profile(), plans = Plans(),
            assumptions = self._assumptions(), frame = frame ) ).run().books
        stamp_display_placements( books, self._profile() )
        return books, BooksTableColumnCatalog.build( Bookkeeper( books ).chart )

    def _survives_re_run( self, type_key : str, group_key : str ):
        """Expand a type then a group to bring its per-class columns onto the frontier, store the lens,
        then adapt it to a brand-new run (fresh UUIDs). Returns (stable tokens under the group at first
        render, tokens that survived the re-run's adapt)."""
        _books1, catalog1 = self._run_catalog()
        lens = ( catalog1.default_definition()
                 .expand( catalog1, BooksColumnKey( type_key ) )
                 .expand( catalog1, BooksColumnKey( group_key ) ) )
        prefix   = group_key + '/'
        stable   = [ token for token in lens.to_storage()[ 'columns' ] if token.startswith( prefix ) ]
        _books2, catalog2 = self._run_catalog()
        restored = BooksTableDefinition.from_storage( lens.to_storage() ).adapt( catalog2 )
        survived = [ key.token for key in restored.column_keys if key.token.startswith( prefix ) ]
        return stable, survived

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

    def test_income_accounts_are_stamped_under_a_per_class_rung( self ):
        books, _catalog = self._run_catalog()
        income_accounts = [ account for account in books.accounts if account.income_tax_class is not None ]
        self.assertTrue( income_accounts )
        for account in income_accounts:
            placement = account.display_placement
            self.assertIsNotNone( placement, f'{account.name} fell back (stamping failed)' )
            path = [ group.key for group in placement.path ]
            self.assertEqual( path[ -1 ], 'inc-' + account.income_tax_class.name.lower() )

    def test_tax_column_layout_survives_a_re_run( self ):
        stable, survived = self._survives_re_run( 'type:EXPENSE', _TAXES_AND_FEES_KEY )
        self.assertTrue( stable, 'expanding Taxes & Fees yielded no per-tax columns' )
        self.assertEqual( sorted( survived ), sorted( stable ) )

    def test_income_column_layout_survives_a_re_run( self ):
        stable, survived = self._survives_re_run( 'type:REVENUE', _INVESTMENT_INCOME_KEY )
        self.assertTrue( stable, 'expanding Investment Income yielded no per-class columns' )
        self.assertEqual( sorted( survived ), sorted( stable ) )
