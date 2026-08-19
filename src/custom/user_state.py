"""User account states and their derivation.

A persisted account progresses through email-anchored states as it gains a more
durable identity. Django's ``AnonymousUser`` (no database row) sits outside that
progression. The derivation here maps *any* request user -- anonymous or
persisted -- onto a single ``UserState`` vocabulary, so call sites branch on one
notion instead of juggling ``is_authenticated`` with ad-hoc email checks.
"""
from common.labeled_enum import LabeledEnum


class UserState( LabeledEnum ):
    """The account states, ordered by how durably the user's identity is anchored.

    Under the identity model the unique ``email`` field holds only a *verified*
    address; an in-flight, unconfirmed address lives in ``pending_email``. So a
    persisted account is one of:

      - **Guest** -- a real account with no email at all (bound to the browser session).
      - **Unverified** -- has claimed an email (pending) but not yet confirmed it.
      - **Verified** -- owns a confirmed email and can recover access from anywhere.

    **Anonymous** is the absence of a persisted account.
    """

    ANONYMOUS   = ( 'Anonymous'  , 'No persisted account; identity lives only in the request.' )
    GUEST       = ( 'Guest'      , 'A persisted account with no email, bound to the browser session.' )
    UNVERIFIED  = ( 'Unverified' , 'Has claimed an email (pending) that is not yet verified.' )
    VERIFIED    = ( 'Verified'   , 'Owns a verified email and can recover access.' )


def user_state( user ) -> UserState:
    """The ``UserState`` of any request user, anonymous or persisted.

    A persisted user reports its own ``account_state``; an ``AnonymousUser`` (or any
    unauthenticated user) is ``ANONYMOUS``. Under the self-hosted single-user mode the
    request carries a real (Guest) account, so it too resolves through ``account_state``.
    """
    if not user.is_authenticated:
        return UserState.ANONYMOUS
    return user.account_state


def is_known( user ) -> bool:
    """Whether ``user`` is a persisted account (Guest or beyond) rather than Anonymous."""
    return user_state( user ) is not UserState.ANONYMOUS
