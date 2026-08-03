"""Reusable form-input widgets shared across the project.

These adorn a plain number input with a currency / percent affix so the "shape"
of a money or percent field lives in one place (the widget), not repeated as
hand-built Bootstrap input-group markup in each template. A field declares its
shape -- forms.DecimalField(widget=MoneyInput()) -- and rendering (via the field
template or a bare {{ field }}) carries the affix automatically.
"""
from django import forms


class _AffixNumberInput(forms.NumberInput):
    """A number input rendered inside a Bootstrap input-group with a currency /
    percent affix. Guarantees the input carries `form-control` (so it joins the
    affix cleanly and sizes correctly), merged with any caller-supplied classes
    such as a JS-hook -- rather than each call site remembering to add it."""

    def __init__( self, attrs = None ):
        attrs   = dict( attrs or {} )
        classes = attrs.get( 'class', '' ).split()
        if 'form-control' not in classes:
            classes.insert( 0, 'form-control' )
        attrs[ 'class' ] = ' '.join( classes )
        super().__init__( attrs )


class MoneyInput( _AffixNumberInput ):
    """A number input with a leading $ (Bootstrap input-group)."""
    template_name = 'django/forms/widgets/money.html'


class PercentInput( _AffixNumberInput ):
    """A number input with a trailing % (Bootstrap input-group)."""
    template_name = 'django/forms/widgets/percent.html'
