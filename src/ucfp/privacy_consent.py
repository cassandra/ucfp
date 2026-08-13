"""The cookie-usage notice: whether to show the banner, and recording acknowledgment.

This is a NOTICE, not a consent gate -- it informs the visitor that the site uses only
necessary cookies (the session cookie that keeps a user signed in), which is compliant
without opt-in. That holds ONLY while the site uses necessary cookies only: adding
analytics or tracking cookies would require a real consent mechanism (accept / reject /
manage), not this banner.
"""
from django.conf import settings


class PrivacyConsent:

    @staticmethod
    def should_show( request ) -> bool:
        """Whether to show the cookie-usage notice on this request.

        Shown only to an anonymous visitor who has not yet acknowledged it: a signed-in
        user already has an account (the footer links the policy), and a self-hosted
        single-user deployment (``SUPPRESS_AUTHENTICATION``) has no public visitor to
        notify.
        """
        if settings.SUPPRESS_AUTHENTICATION:
            return False
        if request.user.is_authenticated:
            return False
        return not request.session_state.cookies_acknowledged

    @staticmethod
    def acknowledge( request ) -> None:
        """Record that the visitor acknowledged the notice, for the rest of the session."""
        request.session_state.cookies_acknowledged = True
        request.session_state.to_session( request )
        return
