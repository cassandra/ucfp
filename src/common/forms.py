"""Shared form building blocks.

MoneyField / PercentField are DecimalField subclasses that default to the currency / percent input
widgets (common.widgets), so a form expresses intent -- "this is money", "this is a percent" -- and the
$ / % affix follows automatically. StyledFormMixin applies Bootstrap control classes to a form's widgets
so its inputs render polished without each field naming the class by hand.
"""
from django import forms
from django.forms.widgets import Input

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


class StyledFormMixin:
    """Applies Bootstrap control classes to each field's widget, so a form renders as polished inputs
    without every field naming the class by hand: text / number / date / file inputs get `form-control`,
    selects get `custom-select`, single checkboxes get `form-check-input`. Hidden inputs, multi-option
    choice widgets (radios and checkbox lists, styled per option), and widgets already carrying a control
    class are left alone. Mix in before `forms.Form` / `forms.ModelForm`."""

    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )
        for field in self.fields.values():
            _apply_control_class( field.widget )


def _apply_control_class( widget ) -> None:
    if isinstance( widget, forms.HiddenInput ):
        return
    if isinstance( widget, ( forms.RadioSelect, forms.CheckboxSelectMultiple ) ):
        return                                       # rendered per option, not a single control
    if isinstance( widget, forms.CheckboxInput ):
        control = 'form-check-input'
    elif isinstance( widget, forms.FileInput ):
        control = 'form-control-file'
    elif isinstance( widget, forms.Select ):
        control = 'custom-select'
    elif isinstance( widget, ( Input, forms.Textarea ) ):
        control = 'form-control'
    else:
        return
    classes = widget.attrs.get( 'class', '' ).split()
    if control not in classes:
        classes.append( control )
        widget.attrs[ 'class' ] = ' '.join( classes )
