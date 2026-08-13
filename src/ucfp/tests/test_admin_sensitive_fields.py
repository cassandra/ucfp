"""The admin exposes record structure for debugging but never the sensitive fields
(the encrypted documents and the entry amount), so the operator has no admin path to
the user's figures."""
from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from ucfp.accounts.models import EntryRecord
from ucfp.inputs.models import PlansRecord, ProfileRecord
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord

_SENSITIVE_FIELDS = [
    ( EntryRecord, 'amount' ),
    ( ProfileRecord, 'data' ),
    ( PlansRecord, 'data' ),
    ( ProjectionRunRecord, 'data' ),
    ( PlanningResultRecord, 'data' ),
]


class AdminHidesSensitiveFieldsTest( TestCase ):

    def setUp( self ):
        user = get_user_model().objects.create_user( email = 'admin@x.test' )
        user.is_staff = True
        user.is_superuser = True
        user.save()
        self.request = RequestFactory().get( '/' )
        self.request.user = user
        return

    def test_sensitive_fields_are_absent_from_the_admin_form( self ):
        for model, field_name in _SENSITIVE_FIELDS:
            with self.subTest( model = model.__name__, field = field_name ):
                model_admin = django_admin.site._registry[ model ]
                form = model_admin.get_form( self.request )
                self.assertNotIn( field_name, form.base_fields )
