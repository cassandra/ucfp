"""run_and_capture composes the layers into a coherent, persisted run that all reloads -- the
data-composition spine: materialize -> run -> persist books -> capture the typed package."""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from common.dataclass_json import from_json_data
from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass
from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.planning.materialization import ForecastFrame
from ucfp.planning.models import ProjectionRunRecord
from ucfp.planning.orchestration import run_and_capture
from ucfp.planning.schemas import ProjectionRun
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType, JurisdictionType
from ucfp.jurisdiction.law import StatuteProfile


class RunAndCaptureTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.organization = Organization.objects.create( name = 'Org' )

    def _profile( self ) -> Profile:
        return Profile(
            subjects = [ SubjectProfile(
                handle = 'subject', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            filing_status = FilingStatus.SINGLE,
            assets = [ AssetProfile(
                handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) ) ] )

    def _plans( self ) -> Plans:
        return Plans()

    def _assumptions( self ) -> Assumptions:
        return Assumptions(
            economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
            statute = StatuteProfile(
                jurisdiction_type = JurisdictionType.US_FEDERAL,
                forecast_type = StatuteForecastType.CURRENT_LAW ) )

    def test_runs_persists_and_reloads_a_coherent_package( self ):
        frame = ForecastFrame(
            start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
            granularity = Duration( 1, TimeUnit.YEAR ) )
        record = run_and_capture(
            self.organization, self._profile(), self._plans(), self._assumptions(), frame,
            label = 'Test run' )

        self.assertEqual( ProjectionRunRecord.objects.count(), 1 )
        record = ProjectionRunRecord.objects.get( pk = record.pk )

        # the typed ProjectionRun (inputs + non-books result) reloads from the record's data
        captured = from_json_data( ProjectionRun, record.data )
        self.assertEqual( captured.profile.subjects[ 0 ].name, 'You' )
        self.assertEqual( len( captured.result.steps ), 5 )            # 2026..2030

        # the books are persisted and a figure derives from them (not duplicated in the run)
        books = BooksOfAccountRepository().load( record.books )
        net_worth = Bookkeeper( books ).ledger.net_worth( through = date( 2026, 12, 31 ) )
        self.assertGreater( net_worth, Decimal( '0' ) )
