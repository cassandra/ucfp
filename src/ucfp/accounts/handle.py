"""The identity of what an account refers to -- the handle the planning layer mints."""
from typing import Protocol


class Handle( Protocol ):
    """A stable, unique identity the planning layer mints for an entity an account refers to
    -- its owner today (the subject whose account it is), and other planner references in
    time. The domain treats it opaquely: it needs only a unique ``__str__``, stamps the
    handle on the account (and, in time, persists its string), and pairs accounts to subjects
    by it. The planning layer owns the scheme; any object with a unique ``__str__`` qualifies,
    and a plain ``str`` is the simplest one."""

    def __str__( self ) -> str:
        ...
