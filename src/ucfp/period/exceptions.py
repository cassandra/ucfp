"""Errors raised by the projection (forecast) engine."""


class ProjectionError( Exception ):
    """Base class for projection-engine errors."""


class MissingAccountError( ProjectionError ):
    """Raised when a projection step requires a chart account that is absent --
    e.g. a cash hub to receive distributions, an income account for a tax-class, or
    the Unrealized Gains equity account for growth. Surfacing it beats silently
    dropping the posting."""
