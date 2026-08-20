"""Idempotent seeding of the system-default parameter sets from the canonical defaults.

A thin CLI wrapper over `seed_default_parameter_sets` (in the shared `management.seeding` module),
where the reusable logic lives so tests can seed without going through the command. Meant to run on
deploy; the summary line is printed at the default verbosity and suppressed by `--verbosity 0`.
"""
from django.core.management.base import BaseCommand

from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets


class Command( BaseCommand ):
    help = 'Seed or refresh the system-default parameter sets, preserving admin modifications.'

    def add_arguments( self, parser ):
        parser.add_argument(
            '--force', action = 'store_true',
            help = 'Refresh even admin-modified system defaults back to the canonical values.' )

    def handle( self, *args, **options ):
        result = seed_default_parameter_sets( force = options[ 'force' ] )
        if options[ 'verbosity' ] >= 1:
            self.stdout.write( self.style.SUCCESS(
                f'Parameter-set seed complete: {result.created} created, {result.refreshed} refreshed, '
                f'{result.preserved} preserved (admin-modified).' ) )
