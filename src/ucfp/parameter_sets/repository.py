"""The read path for the parameter-set library: load a set's typed payload by kind and name.

The single place that turns a stored `ParameterSet` back into its typed aggregate, so callers
(materialization, the admin, the seeder) never touch the raw JSON.
"""
from typing import Optional

from common.dataclass_json import from_json_data

from organization.models import Organization

from .enums import ParameterSetKind
from .models import ParameterSet
from .registry import AGGREGATE_BY_KIND


def load( kind : ParameterSetKind, name : str,
          organization : Optional[ Organization ] = None ):
    """The typed payload of the `(kind, name)` set owned by `organization` (the system default
    when None)."""
    record = ParameterSet.objects.get( kind = kind, label = name, organization = organization )
    return from_json_data( AGGREGATE_BY_KIND[ kind ], record.data )


def economic_parameters( variant_label : str ):
    """The `EconomicParameters` of the economic-outlook preset named `variant_label` -- the first
    (currently only) segment of its schedule. The seed source for a scenario's editable copy."""
    return load( ParameterSetKind.ECONOMIC_OUTLOOK, variant_label ).segments[ 0 ]
