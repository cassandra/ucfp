"""The tax display worksheet is captured with a run: assembled from the engine's per-tax-year worksheets,
persisted in the run JSON, and reloaded intact -- with a run captured before the field existed reloading to
no worksheet (the graceful, no-migration path) -- and the run's worksheet page renders it, org-scoped."""
from datetime import date
from decimal import Decimal

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase

from common.dataclass_json import from_json_data, to_json_data
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.planning.materialization import ForecastFrame
from ucfp.planning.models import ProjectionRunRecord
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.schemas import ProjectionResult, ProjectionRun
from ucfp.planning.views import RunResultsView, RunTaxWorksheetView
from ucfp.session_state import SessionState
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.jurisdiction.tax_worksheet import ColumnCategory


def _profile() -> Profile:
    return Profile(
        subjects = [ SubjectProfile( handle = 'subject', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE,
        assets = [
            AssetProfile( handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                          opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) ),
            AssetProfile( handle = 'stocks', name = 'Stocks', asset_class = AssetClass.STOCKS,
                          opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ),
            AssetProfile( handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                          opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ) ] )


def _assumptions() -> Assumptions:
    return Assumptions(
        economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
        tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )


def _frame() -> ForecastFrame:
    return ForecastFrame(
        start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
        granularity = Duration( 1, TimeUnit.YEAR ) )


def _capture( organization ) -> ProjectionRunRecord:
    return run_and_capture(
        organization, _profile(), Plans(), _assumptions(), _frame(), label = 'Test run' )


class TaxWorksheetCaptureTest( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()
        self.organization = Organization.objects.create( name = 'Org' )

    def _reloaded( self ) -> ProjectionRun:
        record = _capture( self.organization )
        return from_json_data( ProjectionRun, ProjectionRunRecord.objects.get( pk = record.pk ).data )

    def test_the_run_captures_one_worksheet_row_per_tax_year( self ):
        worksheet = self._reloaded().result.tax_worksheet
        self.assertIsNotNone( worksheet )
        self.assertEqual( worksheet.jurisdiction, JurisdictionType.US_FEDERAL )
        self.assertEqual( [ row.year for row in worksheet.years ], [ 2026, 2027, 2028, 2029, 2030 ] )
        self.assertEqual( [ group.category for group in worksheet.groups ],
                          [ ColumnCategory.INCOME, ColumnCategory.INCOME_DERIVED,
                            ColumnCategory.TAXES, ColumnCategory.RATES ] )

    def test_the_worksheet_survives_the_json_round_trip_as_decimals( self ):
        first_year = self._reloaded().result.tax_worksheet.years[ 0 ]
        self.assertIsInstance( first_year.cells[ 'agi' ], Decimal )
        self.assertIn( 'total_tax', first_year.cells )


class BackwardCompatibilityTest( SimpleTestCase ):
    """A run captured before the worksheet field existed has no `tax_worksheet` key in its stored JSON; the
    codec fills the dataclass default, so it reloads with no worksheet rather than failing."""

    def test_a_result_without_the_field_reloads_with_no_worksheet( self ):
        data = to_json_data( ProjectionResult( stopped_early = False, steps = [] ) )
        del data[ 'tax_worksheet' ]                                    # an older record never wrote it
        restored = from_json_data( ProjectionResult, data )
        self.assertIsNone( restored.tax_worksheet )


class RunTaxWorksheetViewTest( TestCase ):

    def setUp( self ):
        seed_default_parameter_sets()
        self.organization = Organization.objects.create( name = 'Org' )

    def _get( self, record, organization ):
        request = RequestFactory().get( f'/run/{ record.uuid }/tax-worksheet/' )
        request.organization = organization
        return RunTaxWorksheetView().get( request, run_uuid = record.uuid )

    def test_the_page_renders_the_worksheet( self ):
        record   = _capture( self.organization )
        response = self._get( record, self.organization )
        self.assertEqual( response.status_code, 200 )
        content = response.content.decode()
        self.assertIn( 'Tax Worksheet', content )                     # the page heading
        self.assertIn( 'run-table-panel', content )                   # the minimize/maximize panel
        self.assertIn( 'Adjusted Gross Income', content )             # a worksheet column label
        self.assertIn( 'tw-age', content )                            # the sticky Age reference column

    def test_the_page_is_scoped_to_the_org( self ):
        record = _capture( self.organization )
        other  = Organization.objects.create( name = 'Other' )
        with self.assertRaises( Http404 ):
            self._get( record, other )


class RunResultsRenderTest( TestCase ):
    """Regression: the run results page must render. Adding a neighboring view once captured
    `RunResultsView`'s own `_notice_row` / `_extra_context` helpers onto the wrong class, 500-erroring the
    page. Nothing rendered this view end-to-end, so it slipped through -- this guards it."""

    def setUp( self ):
        seed_default_parameter_sets()
        self.organization = Organization.objects.create( name = 'Org' )

    def test_the_results_page_renders( self ):
        record  = _capture( self.organization )
        request = RequestFactory().get( f'/run/{ record.uuid }/' )
        request.organization  = self.organization
        request.session       = dict()
        request.session_state = SessionState( current_organization_uuid = str( self.organization.uuid ) )
        response = RunResultsView().get( request, run_uuid = record.uuid )
        self.assertEqual( response.status_code, 200 )
