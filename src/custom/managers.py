from django.contrib import auth
from django.contrib.auth.hashers import make_password
from django.contrib.auth.base_user import BaseUserManager


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def canonicalize_email( self, email ):
        """
        Canonical form of the email used as the account's unique identifier:
        normalized, stripped, and fully lowercased so a person maps to exactly
        one account regardless of how they capitalize their address. Blank or
        whitespace-only input collapses to None (exempt from the unique
        constraint, unlike an empty string).
        """
        if not email:
            return None
        return self.normalize_email( email ).strip().lower() or None

    def _create_user( self, email, password, **extra_fields ):
        """
        Create and save a user with the given email and password.
        """
        email = self.canonicalize_email( email )

        user = self.model( email=email, **extra_fields )
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    def create_guest( self ):
        """Create a Guest: a persisted account with no email and no usable password,
        identified only by its session until an email is later attached. The single
        entry point for the email-less accounts used by anonymous cloud conversion and
        the self-hosted singleton alike.
        """
        return self.create_user()

    def verified_account_for_email( self, email ):
        """The existing account that owns `email` as a *verified* address, or None.

        Since the unique `email` field holds only verified addresses, a match here is
        the collision signal when attaching an email to a Guest. A merely pending
        (unverified) claim on the same address by another account is deliberately not
        matched -- it holds no claim on the identity.
        """
        canonical_email = self.canonicalize_email( email )
        if canonical_email is None:
            return None
        return self.filter( email = canonical_email ).first()

    def create_user(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)

    def with_perm(
        self, perm, is_active=True, include_superusers=True, backend=None, obj=None
    ):
        if backend is None:
            backends = auth._get_backends(return_tuples=True)
            if len(backends) == 1:
                backend, _ = backends[0]
            else:
                raise ValueError(
                    "You have multiple authentication backends configured and "
                    "therefore must provide the `backend` argument."
                )
        elif not isinstance(backend, str):
            raise TypeError(
                "backend must be a dotted import path string (got %r)." % backend
            )
        else:
            backend = auth.load_backend(backend)
        if hasattr(backend, "with_perm"):
            return backend.with_perm(
                perm,
                is_active=is_active,
                include_superusers=include_superusers,
                obj=obj,
            )
        return self.none()
