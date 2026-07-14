"""Cross-cutting enumerations for the input layer."""
from common.labeled_enum import LabeledEnum


class UsageRole( LabeledEnum ):
    """How a persisted input/result record is owned, and therefore how it is managed. `WORKING` records
    are the app-managed working copies of the exploration loop -- overwritten as the user tweaks and
    pruned automatically; `SAVED` records are user-managed and retained until explicitly deleted. This
    partitions Plans, Assumptions, Scenario, and run records so each surface shows only its own set under
    its own retention policy. A single enum (rather than a boolean) leaves room for future planning
    features to own further partitions without a schema change."""

    WORKING = ( 'Working', 'App-managed working copy in the exploration loop; overwritten and pruned.' )
    SAVED   = ( 'Saved', 'User-managed and retained until explicitly deleted.' )
