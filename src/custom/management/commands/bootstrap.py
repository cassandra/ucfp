from django.conf import settings
from django.core.management.base import BaseCommand

from custom.models import CustomUser


class Command( BaseCommand ):
    """
    Initialize the baseline data a deployment needs to be usable:

      - The superuser, created from DJANGO_SUPERUSER_EMAIL/DJANGO_SUPERUSER_PASSWORD
        (Django's built-in "createsuperuser" does not allow passing a password).
      - Any project-specific permission groups.

    Both steps are idempotent, so this is safe to run on every deploy.
    """

    def handle( self, *args, **options ):
        self._create_superuser()
        self._create_groups()
        return

    def _create_superuser( self ):
        admin_email = settings.DJANGO_SUPERUSER_EMAIL
        admin_password = settings.DJANGO_SUPERUSER_PASSWORD
        if not admin_email or not admin_password:
            raise ValueError( 'Need to set "DJANGO_SUPERUSER_EMAIL" and "DJANGO_SUPERUSER_PASSWORD"' )
        if not CustomUser.objects.filter( email = admin_email ).exists():
            CustomUser.objects.create_superuser(
                email = admin_email,
                password = admin_password,
            )
        return

    def _create_groups( self ):
        # TODO: Placeholder for eventual project-specific groups creation.
        return
