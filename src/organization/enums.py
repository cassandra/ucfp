"""Enumerations for the optional organization (multi-tenancy) app."""
from common.labeled_enum import LabeledEnum


class OrganizationRole( LabeledEnum ):
    """A member's role within an organization.

    The role is a *mechanism* only: it names a tier of membership. Mapping a role
    to concrete capabilities is the consuming application's responsibility.
    """

    OWNER   = ( 'Owner'  , 'Full control of the organization, including membership and ownership.' )
    ADMIN   = ( 'Admin'  , 'Elevated privileges short of ownership.' )
    MEMBER  = ( 'Member' , 'Regular member with no special privileges.' )

    @classmethod
    def default(cls):
        return cls.MEMBER


class OrganizationInvitationStatus( LabeledEnum ):
    """Lifecycle state of an organization invitation."""

    WAITING   = ( 'Waiting'  , 'Awaiting the invitee response.' )
    ACCEPTED  = ( 'Accepted' , 'The invitee accepted and joined the organization.' )
    DECLINED  = ( 'Declined' , 'The invitee declined the invitation.' )
    REVOKED   = ( 'Revoked'  , 'The invitation was withdrawn by the organization.' )

    @classmethod
    def default(cls):
        return cls.WAITING
