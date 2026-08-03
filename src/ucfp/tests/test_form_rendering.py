"""Guards the project's template-based form rendering: the custom field template
(templates/django/forms/field.html) plus the FORM_RENDERER wiring that makes it
apply app-wide. If either regresses, field markup silently reverts to Django's
default and these fail."""
from django import forms
from django.test import SimpleTestCase


class _DemoForm(forms.Form):
    amount = forms.DecimalField(label='Amount', help_text='Per month')


class FieldTemplateTest(SimpleTestCase):

    def test_as_field_group_uses_the_themed_field_template(self):
        rendered = str(_DemoForm()['amount'].as_field_group())
        # Themed, compact-muted label wired to the input for accessibility.
        self.assertIn('<label class="text-muted small mb-0 d-block"', rendered)
        self.assertIn('for="id_amount"', rendered)
        self.assertIn('Amount', rendered)
        # Help text and the widget itself.
        self.assertIn('class="form-text text-muted"', rendered)
        self.assertIn('name="amount"', rendered)

    def test_errors_render_with_the_themed_span_and_matching_aria_id(self):
        form = _DemoForm(data={'amount': ''})   # required -> "This field is required."
        form.is_valid()
        rendered = str(form['amount'].as_field_group())
        self.assertIn('<span class="text-danger small d-block"', rendered)
        # The error span id must match the widget's aria-describedby target.
        self.assertIn('id="id_amount_error"', rendered)

    def test_bare_widget_render_is_unaffected_by_the_field_template(self):
        # Plain {{ field }} renders only the widget -- no label, no field template.
        widget = str(_DemoForm()['amount'])
        self.assertIn('name="amount"', widget)
        self.assertNotIn('text-muted small mb-0 d-block', widget)
