import logging
import uuid

from django.db import models
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import managers
from .user_state import UserState

logger = logging.getLogger(__name__)


class CustomUser( AbstractBaseUser, PermissionsMixin ):
    """Mostly a copy of Django's AbstractUser code, but with uuid and email as
    unique fields and without the username field.

    An account carries a ``UserState`` beyond Django's Anonymous/Authenticated split
    (Guest, Verified); ``custom.user_state`` defines and derives it. The field-level
    invariant those states rest on: the unique ``email`` holds only a *verified* address
    -- so its mere presence means Verified -- while an in-flight, unconfirmed one lives in
    the non-unique ``pending_email`` until verification promotes it. A claimed-but-unverified
    address therefore never occupies the unique slot, and no one can block an address they
    do not control.

    The UUID field allows us to have a unique, unchanging field for external references to users.
    """
    # For external referencing
    uuid = models.UUIDField(
        'UUID',
        default = uuid.uuid4,
        unique = True,
        null = False,
        editable = False,
    )
    # All users without emails
    email = models.EmailField(
        _('email address'),
        unique = True,
        null = True,
        blank = True,
    )
    # An address the user has claimed but not yet verified. Unlike `email` it is not
    # unique and never grants recovery: it holds the in-flight claim until verification
    # promotes it into `email` (see `verify_pending_email`).
    pending_email = models.EmailField(
        _('pending email address'),
        null = True,
        blank = True,
    )
    first_name = models.CharField(
        _('first name'),
        max_length = 150,
        blank = True
    )
    last_name = models.CharField(
        _('last name'),
        max_length = 150,
        blank = True
    )
    is_staff = models.BooleanField(
        _('staff status'),
        default = False,
        help_text = _('Designates whether the user can log into this admin site.')
    )
    is_active = models.BooleanField(
        _('active'),
        default = True,
        help_text = _('Designates whether this user should be treated as '
                      'active. Unselect this instead of deleting accounts.')
    )
    date_joined = models.DateTimeField(
        _('date joined'),
        default = timezone.now
    )

    objects = managers.CustomUserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = [ ]

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def __str__(self):
        if self.email:
            return self.email
        return self.uuid_str

    def clean(self):
        super().clean()
        # Canonicalize through the manager so admin/form-created users match the
        # passwordless sign-in path: normalized, lowercased, blank collapsed to
        # NULL (which is exempt from the unique constraint; an empty string is not).
        self.email = self.__class__.objects.canonicalize_email(self.email)
        self.pending_email = self.__class__.objects.canonicalize_email(self.pending_email)
        return

    @property
    def account_state(self) -> UserState:
        """This account's `UserState`, derived from the unique `email` slot: Verified once
        it owns a verified `email`, otherwise a Guest (which may carry a `pending_email` it
        is mid-confirming). A persisted account is never Anonymous."""
        if self.email:
            return UserState.VERIFIED
        return UserState.GUEST

    @property
    def is_guest(self) -> bool:
        return self.account_state is UserState.GUEST

    @property
    def is_verified(self) -> bool:
        return self.account_state is UserState.VERIFIED

    def attach_pending_email(self, email):
        """Claim `email` as this account's pending (unconfirmed) address. It is written to
        `pending_email`, never the unique `email` slot -- only verification promotes an
        address there. The caller must have ruled out an existing verified account for the
        address (`objects.verified_account_for_email`) and is responsible for sending the
        confirmation."""
        self.pending_email = self.__class__.objects.canonicalize_email(email)
        self.save(update_fields = [ 'pending_email' ])
        return

    def verify_pending_email(self):
        """Promote the pending address into the verified `email` slot -- the sole path by
        which an address enters the unique field -- moving the account to Verified. Raises
        if there is no pending address to verify."""
        if not self.pending_email:
            raise ValueError('No pending email to verify.')
        self.email = self.pending_email
        self.pending_email = None
        self.save(update_fields = [ 'email', 'pending_email' ])
        return

    @property
    def uuid_str(self):
        return str(self.uuid)

    def get_full_name(self):
        """
        Returns the first_name plus the last_name, with a space in between.
        """
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def email_user(self, subject, message, from_email=None, **kwargs):
        raise NotImplementedError( f'Use different mechansism to email the user: {self}' )

    @property
    def admin_name(self):
        if self.email:
            return self.email
        if self.first_name:
            return self.first_name
        return self.uuid_str

    @property
    def _email_local_part(self):
        # Fallback display token for users without a name. email is nullable,
        # so fall back to the (always-present) uuid when there is no email.
        if self.email:
            return self.email.split('@')[0]
        return self.uuid_str

    @property
    def long_display_name(self):
        "Last, First when both are set; otherwise whichever name exists, else email/uuid."
        if self.last_name and self.first_name:
            return '%s, %s' % ( self.last_name, self.first_name )
        if self.last_name:
            return self.last_name
        if self.first_name:
            return self.first_name
        return self._email_local_part

    @property
    def short_display_name(self):
        "First name (preferred), else last name, else email/uuid; capped at 20 chars."
        if self.first_name:
            return self.first_name[0:20]
        if self.last_name:
            return self.last_name[0:20]
        return self._email_local_part
