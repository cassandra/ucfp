from django import forms

from .magic_code_generator import MagicCodeGenerator


class MagicCodeForm( forms.Form ):
    """The one-time code entry. It carries only the code: the account it applies to is bound to the
    session server-side when the code is issued (see MagicCodeGenerator), never supplied by the form."""

    magic_code = forms.CharField(
        label = '',
        max_length = 2 * MagicCodeGenerator.MAGIC_CODE_LENGTH,
        widget = forms.TextInput( attrs = { 'autofocus': 'autofocus',
                                            'placeholder': 'one-time code',
                                            'width': str( 2 * MagicCodeGenerator.MAGIC_CODE_LENGTH ) } ),
        required = True )
