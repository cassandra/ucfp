"""The edit-in-place view for plan events (#210 Phase 4): a POST replaces the event at its index and
persists, an invalid edit is refused without touching the stored plan, and a stale/non-editable index is a
no-op. These exercise the `EventEditView` end to end (the form/handler logic is unit-tested in
`test_events.py`); there are no other client tests for the events add/edit/delete views, so this closes the
persistence path that a positional-replace bug would slip through.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organization.models import Organization

from ucfp.inputs.plans.enums import EventKind
from ucfp.inputs.plans.repository import create_plans, latest_plans, load_plans, save_plans
from ucfp.inputs.plans.schemas import PlanEvent, Plans
from ucfp.inputs.profile.repository import save_profile
from ucfp.inputs.profile.schemas import Profile

User = get_user_model()


def _payment( amount, label ) -> PlanEvent:
    return PlanEvent( kind = EventKind.GENERAL_PAYMENT, date = date( 2030, 8, 1 ),
                      amount = Decimal( amount ), label = label )


class EventEditViewTest( TestCase ):

    def setUp( self ):
        self.owner = User.objects.create_user( email = 'owner@x.test' )
        self.org   = Organization.objects.create_for_owner( self.owner, 'Shared' )
        save_profile( self.org, Profile() )
        # Two payments, so an edit at index 0 must leave index 1 untouched.
        self.record = create_plans( self.org )
        save_plans( self.record, Plans(
            events = [ _payment( '40000', 'College Tuition' ), _payment( '9000', 'Wedding' ) ] ) )
        self.client.force_login( self.owner )
        session = self.client.session
        session[ 'current_organization_uuid' ] = str( self.org.uuid )
        session.save()

    def _stored_events( self ):
        return load_plans( latest_plans( self.org ) ).events

    def _post_edit( self, index, data ):
        return self.client.post( reverse( 'event_edit', kwargs = { 'index': index } ), data )

    def test_a_valid_edit_replaces_the_event_at_its_index_and_persists( self ):
        response = self._post_edit(
            0, { 'label': 'College Tuition', 'amount': '55000', 'date': '2030-08',
                 'recurring': 'once' } )
        self.assertEqual( response.status_code, 200 )
        events = self._stored_events()
        self.assertEqual( events[ 0 ].amount, Decimal( '55000' ) )      # index 0 updated
        self.assertEqual( events[ 0 ].label, 'College Tuition' )
        self.assertEqual( events[ 1 ], _payment( '9000', 'Wedding' ) )  # index 1 untouched

    def test_an_invalid_edit_is_refused_without_touching_the_stored_plan( self ):
        # Recurring with an end before the start fails validation, so nothing is persisted.
        before   = self._stored_events()
        response = self._post_edit(
            0, { 'label': 'College Tuition', 'amount': '55000', 'date': '2032-08',
                 'recurring': 'recurring', 'recur_count': '1', 'recur_unit': 'YEAR',
                 'finish': '2030-08' } )
        self.assertEqual( response.status_code, 200 )
        self.assertEqual( self._stored_events(), before )              # unchanged

    def test_an_out_of_range_index_is_a_no_op( self ):
        before   = self._stored_events()
        response = self._post_edit( 9, { 'amount': '1', 'date': '2030-08', 'recurring': 'once' } )
        self.assertEqual( response.status_code, 200 )
        self.assertEqual( self._stored_events(), before )

    def test_the_edit_form_opens_pre_filled( self ):
        response = self.client.get( reverse( 'event_edit', kwargs = { 'index': 0 } ) )
        self.assertEqual( response.status_code, 200 )
        body = response.content.decode()
        self.assertIn( 'College Tuition', body )                       # seeded purpose
        self.assertIn( reverse( 'event_edit', kwargs = { 'index': 0 } ), body )   # posts back to edit
        self.assertIn( '>Save<', body )
