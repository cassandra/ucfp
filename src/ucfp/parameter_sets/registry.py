"""The map from a parameter-set kind to its typed payload schema -- the single place a loader or
seeder consults to (de)serialize a `ParameterSet`'s `data`."""
from .enums import ParameterSetKind
from .schemas import EconomicOutlookSchedule, ExpenseCatalog

AGGREGATE_BY_KIND = {
    ParameterSetKind.ECONOMIC_OUTLOOK: EconomicOutlookSchedule,
    ParameterSetKind.EXPENSE_CATALOG: ExpenseCatalog,
}
