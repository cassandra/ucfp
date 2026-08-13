"""The sensitive input and run documents are encrypted at rest; the lower-sensitivity
ones (assumptions, seeded parameter sets) stay plaintext, per the chosen scope."""
import json
from datetime import date

from cryptography.fernet import Fernet
from django.db import connection
from django.test import TestCase, override_settings

from organization.models import Organization

from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.models import AssumptionsRecord, PlansRecord, ProfileRecord
from ucfp.parameter_sets.enums import ParameterSetKind
from ucfp.parameter_sets.models import ParameterSet
from ucfp.planning.enums import PlanningFeature
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord

_KEY = Fernet.generate_key().decode()
_PAYLOAD = { 'secret': 12345 }


def _raw_data( instance ):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT data FROM {instance._meta.db_table} WHERE id = %s', [ instance.pk ] )
        return cursor.fetchone()[ 0 ]


@override_settings( FIELD_ENCRYPTION_CODEC = 'fernet', FIELD_ENCRYPTION_KEYS = ( _KEY, ) )
class EncryptedDocumentScopeTest( TestCase ):

    def setUp( self ):
        self.organization = Organization.objects.create( name = 'Org' )
        return

    def _assert_encrypted( self, instance ):
        instance.refresh_from_db()
        self.assertEqual( instance.data, _PAYLOAD )              # ORM round-trips the document
        with self.assertRaises( json.JSONDecodeError ):         # but it is opaque at rest
            json.loads( _raw_data( instance ) )

    def _assert_plaintext( self, instance ):
        instance.refresh_from_db()
        self.assertEqual( instance.data, _PAYLOAD )
        self.assertEqual( json.loads( _raw_data( instance ) ), _PAYLOAD )   # readable JSON at rest

    def test_profile_document_is_encrypted( self ):
        self._assert_encrypted( ProfileRecord.objects.create(
            organization = self.organization, label = 'P',
            effective_date = date( 2026, 1, 1 ), data = _PAYLOAD ) )

    def test_plans_document_is_encrypted( self ):
        self._assert_encrypted( PlansRecord.objects.create(
            organization = self.organization, label = 'Pl', data = _PAYLOAD ) )

    def test_projection_run_document_is_encrypted( self ):
        books = BooksOfAccountRecord.objects.create( organization = self.organization )
        self._assert_encrypted( ProjectionRunRecord.objects.create(
            organization = self.organization, books = books, label = 'R', data = _PAYLOAD ) )

    def test_planning_result_document_is_encrypted( self ):
        books = BooksOfAccountRecord.objects.create( organization = self.organization )
        run = ProjectionRunRecord.objects.create(
            organization = self.organization, books = books, label = 'R', data = {} )
        self._assert_encrypted( PlanningResultRecord.objects.create(
            organization = self.organization, feature = PlanningFeature.FINANCIAL_FORECAST,
            run = run, label = 'Res', data = _PAYLOAD ) )

    def test_assumptions_document_stays_plaintext( self ):
        self._assert_plaintext( AssumptionsRecord.objects.create(
            organization = self.organization, label = 'A', data = _PAYLOAD ) )

    def test_parameter_set_document_stays_plaintext( self ):
        self._assert_plaintext( ParameterSet.objects.create(
            kind = ParameterSetKind.ECONOMIC_OUTLOOK, label = 'PS', data = _PAYLOAD ) )
