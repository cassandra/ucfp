import html
from typing import Dict

from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.generic import View


class EmailPreviewView( View ):
    """
    Base view for visually previewing an email (subject + text body + HTML body)
    without sending it, to check formatting.

    Subclass it in an app's ``tests/ui/`` module: set ``app_name`` and provide
    ``get_extra_context()``. The email templates are resolved as
    ``{app_name}/emails/{view_name}_subject.txt``,
    ``{app_name}/emails/{view_name}_message.txt`` and ``..._message.html``,
    where ``view_name`` comes from the ``email_type`` URL kwarg.
    """

    @property
    def app_name( self ):
        raise NotImplementedError('Subclasses must override this')

    def get_extra_context( self, email_type : str ) -> Dict[ str, object ]:
        raise NotImplementedError('Subclasses must override this')

    def get( self, request, *args, **kwargs ):
        context = self.get_context_for_email_message( request, *args, **kwargs )
        return self.email_preview_response(
            request = request,
            app_name = self.app_name,
            view_name = context.get('email_type', 'NOT_SPECIFIED'),
            context = context,
        )

    def get_context_for_email_message( self, request, *args, **kwargs ) -> Dict[ str, object ]:
        email_type = kwargs.get('email_type')
        context = {
            'email_type': email_type,
        }
        context.update( self.get_extra_context( email_type = email_type ))
        return context

    def email_preview_response( self, request, app_name : str, view_name : str, context : dict ):
        context.update({
            'view_name': view_name,
            'BASE_URL': ' ',
            'UNSUBSCRIBE_URL': 'https://example.com/unsubscribe',
            'USER_HOME_URL': 'https://example.com/home',
        })

        # The HTML email carries its own inline CSS that must not clash with the
        # site's main CSS, so it is displayed inside an <iframe srcdoc="...">.
        # srcdoc needs the markup pre-rendered, so render and HTML-escape it here.
        body_html_template = f'{app_name}/emails/{view_name}_message.html'
        body_html = render_to_string( body_html_template, context )
        escaped_email_html = html.escape( body_html )

        context.update({
            'subject_text_template': f'{app_name}/emails/{view_name}_subject.txt',
            'body_text_template': f'{app_name}/emails/{view_name}_message.txt',
            'body_html_template': body_html_template,
            'body_html': escaped_email_html,
        })
        return render( request, 'testing/ui/modals/email_preview.html', context )
