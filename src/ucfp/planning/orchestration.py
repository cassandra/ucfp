"""Run a forecast and capture it as a `ProjectionRunRecord`.

The composition point that ties the layers together: materialize the user's Profile + Plans +
Assumptions + frame into engine parameters, run the engine, persist the books through the accounts
repository, and record the inputs and non-books result as a coherent, immutable package.
"""
from datetime import datetime
from typing import Optional

from django.utils.dateformat import format as format_datetime

from common.dataclass_json import to_json_data

from organization.models import Organization

from ucfp.accounts.repository import BooksOfAccountRepository
from ucfp.forecast.forecast import Forecast
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.jurisdiction.tax_worksheet import TaxDisplayWorksheet

from .display_placement import stamp_display_placements
from .materialization import ForecastFrame, materialize
from .models import ProjectionRunRecord
from .schemas import NoticeRecord, ProjectionResult, ProjectionRun, StepResult


def run_and_capture(
        organization: Organization, profile: Profile, plans: Plans, assumptions: Assumptions,
        frame: ForecastFrame, label: str, source_label: Optional[ str ] = None ) -> ProjectionRunRecord:
    """Materialize, run, persist the books, and capture the run as a `ProjectionRunRecord`. `label` is the
    run's initial title (editable later); `source_label` is the scenario it came from, preserved so a
    rename does not lose that provenance (defaults to `label`)."""
    parameters   = materialize(
        profile = profile, plans = plans, assumptions = assumptions, frame = frame )
    result       = Forecast( parameters ).run()
    stamp_display_placements( result.books, profile )
    books_record = BooksOfAccountRepository().save( result.books, organization )
    captured     = ProjectionRun(
        profile = profile, plans = plans, assumptions = assumptions, frame = frame,
        result = _summarize( result ) )
    return ProjectionRunRecord.objects.create(
        organization = organization, books = books_record, label = label,
        source_label = label if source_label is None else source_label,
        data = to_json_data( captured ) )


def run_title( source_label: str, run_at: datetime ) -> str:
    """A captured run's default title: the scenario it came from and when it ran, so it reads as a run
    rather than as its scenario (a run named just "My Scenario" is indistinguishable from the
    scenario). `source_label` stays the bare scenario name -- kept separately as provenance -- and
    `run_at` is the run's local timestamp, formatted to match how the run list shows it."""
    return f'{source_label} - Run at {format_datetime( run_at, "M j, Y, g:i a" )}'


def _summarize( result ) -> ProjectionResult:
    """The non-books result data worth persisting (figures derivable from the books are not)."""
    return ProjectionResult(
        stopped_early = result.stopped_early,
        steps         = [ _step( step ) for step in result.steps ],
        tax_worksheet = _tax_worksheet( result ) )


def _tax_worksheet( result ) -> Optional[ TaxDisplayWorksheet ]:
    """The run's whole tax display worksheet, assembled from the per-year worksheets the engine attached to
    each tax-year-settling step: one shared column schema (stable across the run's years) and one value row
    per tax year, in order. None when no step settled a tax year."""
    yearly = [ step.result.tax_worksheet for step in result.steps if step.result.tax_worksheet is not None ]
    if not yearly:
        return None
    # Take the schema from the first year and concatenate every year's row. This holds because the revenue
    # chart is created complete at baseline (forecast `_create_income_accounts` / `_create_asset_income_
    # accounts`) and income columns key on the stable account UUID, so every year's schema is identical; a
    # future change that created a revenue account mid-run would need this revisited (the year-0 schema
    # would omit it).
    rows = tuple( row for worksheet in yearly for row in worksheet.years )
    return TaxDisplayWorksheet(
        jurisdiction = yearly[ 0 ].jurisdiction, groups = yearly[ 0 ].groups, years = rows )


def _step( step ) -> StepResult:
    return StepResult(
        start_date  = step.span.start_date,
        end_date    = step.span.end_date,
        is_depleted = step.result.is_depleted,
        notices     = [ NoticeRecord( kind = notice.kind, severity = notice.severity,
                                      amount = notice.amount, detail = notice.detail )
                        for notice in step.result.notices ] )
