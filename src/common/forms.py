"""Semantic form fields that pair a value's type with its display shape.

MoneyField / PercentField are DecimalField subclasses that default to the
currency / percent input widgets (common.widgets), so a form expresses intent --
"this is money", "this is a percent" -- and the $ / % affix follows
automatically, rather than each template hand-building an input-group.
"""
from django import forms

from common.widgets import MoneyInput, PercentInput


class MoneyField(forms.DecimalField):
    """A DecimalField shown as a currency input (leading $)."""
    widget = MoneyInput


class PercentField(forms.DecimalField):
    """A DecimalField shown as a percent input (trailing %)."""
    widget = PercentInput
