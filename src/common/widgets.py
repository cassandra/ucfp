"""Reusable form-input widgets shared across the project.

These adorn a plain input with a currency / percent affix so the "shape" of a
money or percent field lives in one place (the widget), not repeated as hand-built
Bootstrap input-group markup in each template. A field declares its shape --
forms.DecimalField(widget=MoneyInput()) -- and rendering (via the field template or
a bare {{ field }}) carries the affix automatically.

Money is a *text* input (not number) so its value can carry thousands separators;
inputs.js groups them as the user types and MoneyField strips them on the way in.
Percent stays a number input (small rates, no grouping needed).
"""
from django import forms


class _AffixInput:
    """Guarantees an affixed input carries `form-control` (so it joins the input-group
    affix cleanly and sizes correctly), merged with any caller-supplied classes such as
    a JS-hook -- rather than each call site remembering to add it. Mixed in before the
    concrete `forms.Widget` base."""

    def __init__( self, attrs = None ):
        attrs   = dict( attrs or {} )
        classes = attrs.get( 'class', '' ).split()
        if 'form-control' not in classes:
            classes.insert( 0, 'form-control' )
        attrs[ 'class' ] = ' '.join( classes )
        super().__init__( attrs )


class MoneyInput( _AffixInput, forms.TextInput ):
    """A currency input: a number with a leading $ (Bootstrap input-group). A *text* input
    (not number) so the value can carry thousands separators -- inputs.js groups them as the
    user types and MoneyField strips them before the decimal parse. `inputmode='decimal'` brings
    up the numeric keypad on mobile; the `js-money` hook marks the input for the grouping script
    (this string mirrors AppConst.MONEY_INPUT_CLASS, which inputs.js reads)."""
    template_name = 'django/forms/widgets/money.html'

    def __init__( self, attrs = None ):
        attrs = dict( attrs or {} )
        attrs.setdefault( 'inputmode', 'decimal' )
        classes = attrs.get( 'class', '' ).split()
        if 'js-money' not in classes:
            classes.append( 'js-money' )
        attrs[ 'class' ] = ' '.join( classes )
        super().__init__( attrs )


class PercentInput( _AffixInput, forms.NumberInput ):
    """A number input with a trailing % (Bootstrap input-group)."""
    template_name = 'django/forms/widgets/percent.html'
