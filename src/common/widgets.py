"""Reusable form-input widgets shared across the project.

These adorn a plain number input with a currency / percent affix so the "shape"
of a money or percent field lives in one place (the widget), not repeated as
hand-built Bootstrap input-group markup in each template. A field declares its
shape -- ``forms.DecimalField(widget=MoneyInput())`` -- and rendering (via the
field template or a bare ``{{ field }}``) carries the affix automatically.
"""
from django import forms


class MoneyInput(forms.NumberInput):
    """A number input with a leading ``$`` (Bootstrap input-group)."""
    template_name = 'django/forms/widgets/money.html'


class PercentInput(forms.NumberInput):
    """A number input with a trailing ``%`` (Bootstrap input-group)."""
    template_name = 'django/forms/widgets/percent.html'
