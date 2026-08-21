class MethodNotAllowedError( Exception ):
    pass


class DataNotAvailableError( Exception ):
    """Requested data does not exist yet and the current request may not create it -- e.g. a read-only
    member viewing an input a writer never set up. Carries a user-facing message; surfaced as a friendly
    "not available yet" response by the exception middleware."""
    pass


class ForceRedirectException( Exception ):

    def __init__( self, url, message = 'Force redirect' ):
        self._url = url
        super().__init__( message )
        return

    @property
    def url(self):
        return self._url


class ForceSynchronousException( Exception ):
    pass
