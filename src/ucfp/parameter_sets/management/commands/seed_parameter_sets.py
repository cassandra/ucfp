"""Idempotent seeding of the system-default parameter sets from the canonical defaults.

Creates a missing default, refreshes one an admin has never touched (free updates on app
update), and preserves one an admin has modified. Re-runnable; meant to run on deploy.
"""
from django.core.management.base import BaseCommand

from common.dataclass_json import to_json_data

from ucfp.parameter_sets.defaults import canonical_defaults
from ucfp.parameter_sets.models import ParameterSet


class Command( BaseCommand ):
    help = 'Seed or refresh the system-default parameter sets, preserving admin modifications.'

    def add_arguments( self, parser ):
        parser.add_argument(
            '--force', action = 'store_true',
            help = 'Refresh even admin-modified system defaults back to the canonical values.' )

    def handle( self, *args, **options ):
        force = options[ 'force' ]
        created = refreshed = preserved = 0
        for kind, presets in canonical_defaults().items():
            for variant, aggregate in presets.items():
                name = variant.label
                data = to_json_data( aggregate )
                record = ParameterSet.objects.filter(
                    kind = kind, label = name, organization = None ).first()
                if record is None:
                    ParameterSet.objects.create(
                        kind = kind, label = name, organization = None,
                        data = data, seeded_data = data )
                    created += 1
                elif force or not record.is_modified:
                    record.data = data
                    record.seeded_data = data
                    record.save(
                        update_fields = [ 'data', 'seeded_data', 'updated_datetime' ] )
                    refreshed += 1
                else:
                    preserved += 1
        self.stdout.write( self.style.SUCCESS(
            f'Parameter-set seed complete: {created} created, {refreshed} refreshed, '
            f'{preserved} preserved (admin-modified).' ) )
