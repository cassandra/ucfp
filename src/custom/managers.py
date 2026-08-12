from django.contrib import auth
from django.contrib.auth.hashers import make_password
from django.contrib.auth.base_user import BaseUserManager
from django.db import IntegrityError


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

    def get_or_create_by_email( self, email ):
        """
        Return (user, created) for the canonicalized email, creating a
        password-less account the first time an address is seen. This is the
        entry point for passwordless sign-in: an unknown email becomes a new
        account rather than a dead end.
        """
        canonical_email = self.canonicalize_email( email )
        if canonical_email is None:
            raise ValueError( 'Cannot get or create a user without an email.' )

        existing_user = self.filter( email = canonical_email ).first()
        if existing_user is not None:
            return existing_user, False
        try:
            return self.create_user( email = canonical_email ), True
        except IntegrityError:
            # A concurrent request created this account between our check and
            # our insert; the unique constraint caught it, so re-fetch.
            return self.get( email = canonical_email ), False

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
