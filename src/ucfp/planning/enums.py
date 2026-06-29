"""Enums for the planning-feature layer."""
from common.labeled_enum import LabeledEnum


class PlanningFeature( LabeledEnum ):
    """Which planning feature produced a result -- the tag on a `PlanningResultRecord` that ties a
    shared, feature-agnostic engine run to the perspective that ran it. Financial Forecasting is the
    only built one; the rest are declared so results can be tagged once they exist."""

    FINANCIAL_FORECAST = ( 'Financial Forecast', 'Project one set of facts and assumptions forward.' )
    RETIREMENT_TIMING  = ( 'Retirement Timing', 'Find the earliest feasible retirement date.' )
    SOCIAL_SECURITY    = ( 'Social Security', 'Compare Social Security claiming strategies.' )
    CASH_FLOW          = ( 'Cash Flow', 'Near-term cash sufficiency over the next ~12 months.' )
