"""The reusable seeding of system-default parameter sets, shared by the `seed_parameter_sets`
management command and by tests that need the seeded library.

It lives under `management/` (not beside the runtime read path in `repository.py`) because seeding is
a deploy/admin operation, not part of the request-serving code -- and so the command and the tests
share the logic directly, rather than tests driving it through `call_command`.

Idempotent: creates a missing default, refreshes one an admin has never touched (free updates on app
update), and preserves one an admin has modified. Re-runnable; meant to run on deploy.
"""
from dataclasses import dataclass

from common.dataclass_json import to_json_data

from ucfp.parameter_sets.defaults import canonical_defaults
from ucfp.parameter_sets.models import ParameterSet


@dataclass( frozen = True )
class SeedResult:
    """How a seed run resolved the canonical defaults: how many were newly created, refreshed in
    place (untouched by an admin), or preserved (admin-modified, so left alone)."""
    created   : int = 0
    refreshed : int = 0
    preserved : int = 0


def seed_default_parameter_sets( force : bool = False ) -> SeedResult:
    """Seed or refresh the system-default parameter sets from the canonical code defaults, preserving
    admin modifications unless `force`. Returns the per-outcome counts."""
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
    return SeedResult( created = created, refreshed = refreshed, preserved = preserved )
