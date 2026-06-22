"""Errors raised by the projection (forecast) engine.

A missing chart account is an accounts-domain concern, so it is
`ucfp.accounts.exceptions.MissingAccountError`, raised both by the `Bookkeeper` and by the
projection steps -- there is no projection-specific variant.
"""


class ProjectionError( Exception ):
    """Base class for projection-engine errors."""
