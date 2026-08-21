"""Seed the read-only sample household from the committed fixture and generate its forecast.

Thin wrapper over `onboarding.seeding.seed_sample_org` (the reusable, tested logic). Idempotent; `--force`
refreshes the data records. Runs after `bootstrap` (the superuser owner) and `seed_parameter_sets` (the
run needs seeded law/outlook) in the setup scripts.
"""
from django.core.management.base import BaseCommand, CommandError

from ucfp.onboarding.seeding import NoSuperuserError, seed_sample_org


class Command( BaseCommand ):
    help = ( 'Seed the read-only sample household from the committed fixture and generate its forecast. '
             'Idempotent; --force refreshes the data records.' )

    def add_arguments( self, parser ):
        parser.add_argument( '--force', action = 'store_true',
                             help = 'Refresh the sample data even if it already exists.' )

    def handle( self, *args, **options ):
        try:
            result = seed_sample_org( force = options[ 'force' ] )
        except NoSuperuserError as error:
            raise CommandError( str( error ) )
        if options[ 'verbosity' ] >= 1:
            self.stdout.write( self.style.SUCCESS(
                f"Sample household '{result.organization.name}' {result.action}." ) )
