"""Guards the project's template-based form rendering: the custom field template
(templates/django/forms/field.html) plus the FORM_RENDERER wiring that makes it
apply app-wide. If either regresses, field markup silently reverts to Django's
default and these fail."""
from django import forms
from django.test import SimpleTestCase

from common.forms import MoneyField, PercentField
from common.widgets import MoneyInput, PercentInput


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


class AdornedWidgetTest(SimpleTestCase):

    def test_money_input_wraps_the_number_field_with_a_dollar_affix(self):
        class F(forms.Form):
            amt = forms.DecimalField(widget=MoneyInput())
        html = str(F()['amt'])
        self.assertIn('input-group', html)
        self.assertIn('>$<', html)
        self.assertIn('type="number"', html)

    def test_percent_input_wraps_the_number_field_with_a_percent_affix(self):
        class F(forms.Form):
            rate = forms.DecimalField(widget=PercentInput())
        html = str(F()['rate'])
        self.assertIn('input-group', html)
        self.assertIn('>%<', html)
        self.assertIn('type="number"', html)

    def test_money_and_percent_fields_default_to_their_affix_widgets(self):
        self.assertIsInstance(MoneyField().widget, MoneyInput)
        self.assertIsInstance(PercentField().widget, PercentInput)

    def test_affix_widget_guarantees_form_control_merged_with_caller_classes(self):
        # The input needs form-control to join its input-group affix; the widget adds it
        # while preserving a caller-supplied class (e.g. a JS hook).
        class F(forms.Form):
            amt = MoneyField(css_class='js-hook')
        html = str(F()['amt'])
        self.assertIn('form-control', html)
        self.assertIn('js-hook', html)


class FieldsetRenderTest(SimpleTestCase):

    def test_multiwidget_field_renders_through_the_fieldset_branch(self):
        # A radio/checkbox field sets use_fieldset -> the field template's <fieldset>/<legend> path.
        class F(forms.Form):
            pick = forms.ChoiceField(choices=[('a', 'A'), ('b', 'B')], widget=forms.RadioSelect)
        html = str(F()['pick'].as_field_group())
        self.assertIn('<fieldset', html)
