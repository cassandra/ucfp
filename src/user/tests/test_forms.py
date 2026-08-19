import logging

from django import forms
from django.test import TestCase

from user.forms import MagicCodeForm
from user.magic_code_generator import MagicCodeGenerator

logging.disable(logging.CRITICAL)


class TestMagicCodeForm(TestCase):

    def test_form_has_only_the_code_field(self):
        # The account is bound to the session server-side, so the form carries only the code.
        form = MagicCodeForm()
        self.assertEqual( list( form.fields.keys() ), [ 'magic_code' ] )

    def test_magic_code_field_configuration(self):
        field = MagicCodeForm().fields['magic_code']
        self.assertIsInstance( field, forms.CharField )
        self.assertEqual( field.max_length, 2 * MagicCodeGenerator.MAGIC_CODE_LENGTH )
        self.assertTrue( field.required )
        self.assertEqual( field.label, '' )
        self.assertIsInstance( field.widget, forms.TextInput )

    def test_valid_with_a_code(self):
        form = MagicCodeForm( data = { 'magic_code': 'abc123' } )
        self.assertTrue( form.is_valid() )
        self.assertEqual( form.cleaned_data['magic_code'], 'abc123' )

    def test_invalid_without_a_code(self):
        form = MagicCodeForm( data = { 'magic_code': '' } )
        self.assertFalse( form.is_valid() )
        self.assertIn( 'magic_code', form.errors )

    def test_oversized_code_is_rejected(self):
        oversized = 'x' * ( 2 * MagicCodeGenerator.MAGIC_CODE_LENGTH + 1 )
        form = MagicCodeForm( data = { 'magic_code': oversized } )
        self.assertFalse( form.is_valid() )
        self.assertIn( 'magic_code', form.errors )
