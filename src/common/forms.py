"""Semantic form fields that pair a value's type with its display shape.

MoneyField / PercentField are DecimalField subclasses that default to the
currency / percent input widgets (common.widgets), so a form expresses intent --
"this is money", "this is a percent" -- and the $ / % affix follows
automatically, rather than each template hand-building an input-group.
"""
from django import forms

from common.widgets import MoneyInput, PercentInput


class _AffixField( forms.DecimalField ):
    """A DecimalField whose default widget renders a currency / percent affix.

    Pass `css_class` to add a class (e.g. a JS-hook) to that affix widget without
    naming the widget -- the field's own widget type is used, so the field and
    its affix can never drift apart."""

    def __init__( self, *, css_class = None, **kwargs ):
        if css_class is not None:
            kwargs.setdefault( 'widget', self.widget( attrs = { 'class' : css_class } ) )
        super().__init__( **kwargs )


class MoneyField( _AffixField ):
    """A DecimalField shown as a currency input (leading $)."""
    widget = MoneyInput


class PercentField( _AffixField ):
    """A DecimalField shown as a percent input (trailing %)."""
    widget = PercentInput
