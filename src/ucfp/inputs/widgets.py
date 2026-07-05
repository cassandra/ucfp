"""Shared form widgets for the inputs area.

`IsoDateInput` is the single presentation for a date field. It renders and parses the canonical ISO
`YYYY-MM-DD` the server reads, and tags the input so `inputs.js` enhances it with a date picker tuned
to the field's planning `context`: birthdates sit decades in the past, planning dates decades ahead,
so the picker must not be anchored to the current month. Without JavaScript the field degrades to a
plain ISO text box, which the server still accepts -- the picker is a progressive enhancement.
"""
from django import forms

from ucfp.environment.constants import AppConst


class IsoDateInput( forms.DateInput ):
    """A date input rendered/parsed as canonical ISO and hooked for picker enhancement. `context` is
    one of `AppConst.DATE_CONTEXT_*` and rides along as a data-attribute the client reads to tune the
    picker; it defaults to the common forward-looking case."""

    ISO_FORMAT = '%Y-%m-%d'

    def __init__( self, *, context = AppConst.DATE_CONTEXT_FUTURE, attrs = None ):
        hooks = {
            'class'                                   : AppConst.DATE_FIELD_CLASS,
            f'data-{AppConst.DATE_CONTEXT_DATA_ATTR}' : context,
            'autocomplete'                            : 'off',
            'placeholder'                             : 'YYYY-MM-DD',
        }
        hooks.update( attrs or {} )
        super().__init__( attrs = hooks, format = self.ISO_FORMAT )
