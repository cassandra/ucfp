class OrganizationError( Exception ):
    """Base class for organization-domain errors."""


class LastActiveOwnerError( OrganizationError ):
    """Raised when an operation would leave an organization with no active owner."""


class InvitationError( OrganizationError ):
    """Base class for invitation lifecycle errors."""


class AlreadyActiveMemberError( InvitationError ):
    """Raised when inviting a user who is already an active member of the organization."""


class DuplicateInvitationError( InvitationError ):
    """Raised when a pending invitation already exists for the email and organization."""


class InvitationStateError( InvitationError ):
    """Raised when a lifecycle action is attempted on a non-pending invitation."""


class InvitationRecipientMismatchError( InvitationError ):
    """Raised when the accepting user is neither the invited user nor a match for
    the invitation email."""
