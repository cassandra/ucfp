"""Typed shapes for a captured forecast run.

A `ProjectionRunRecord` persists a coherent package -- the inputs that produced a forecast
(Profile, Plans, run frame) and its outputs -- so a result can be inspected later and traced
to exactly what produced it. The books are persisted separately (via the accounts repository);
any figure derivable from them -- net worth, cash, balances over time -- is *not* duplicated
here. The typed `ProjectionRun` below is the JSON-serialized part: the input snapshot and the
non-books result (whether it stopped early and each interval's notices).
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from ucfp.jurisdiction.tax_worksheet import TaxDisplayWorksheet
from ucfp.period.results import NoticeKind, NoticeSeverity
from ucfp.inputs.profile.schemas import Profile
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.assumptions.schemas import Assumptions

from .materialization import ForecastFrame


@dataclass( frozen = True )
class NoticeRecord:
    """A planning insight the run surfaced (a captured `Notice`): its kind, severity, the figure
    it carries, and `detail` naming what that figure measures. The link to the originating
    transaction is omitted until drill-down needs it."""
    kind: NoticeKind
    severity: NoticeSeverity
    amount: Optional[ Decimal ] = None
    detail: Optional[ str ]     = None


@dataclass( frozen = True )
class StepResult:
    """One interval's non-books outcome: its span, whether net worth was depleted, and the
    notices raised. Per-step figures are derived from the persisted books, not stored here."""
    start_date: date
    end_date: date
    is_depleted: bool = False
    notices: list[ NoticeRecord ] = field( default_factory = list )


@dataclass( frozen = True )
class ProjectionResult:
    """A run's non-books result: whether it stopped early, each interval's step, and the tax display
    worksheet -- the per-tax-year intermediate figures behind the run's taxes, assembled from the years the
    engine assessed (None for a run captured before the worksheet existed, or one that assessed no tax
    year). Unlike per-step figures, the worksheet's inputs (AGI, deductions, rates) are not in the books, so
    it is persisted here rather than re-derived."""
    stopped_early: bool = False
    steps: list[ StepResult ] = field( default_factory = list )
    tax_worksheet: Optional[ TaxDisplayWorksheet ] = None


@dataclass( frozen = True )
class ProjectionRun:
    """The typed package a `ProjectionRunRecord` stores in its `data`: the inputs (snapshotted
    for provenance, since profile, plans, and assumptions drift over time) and the non-books result.
    The persisted books are referenced separately, by the record's FK -- exactly as a `ProfileRecord`
    holds a typed `Profile` plus its `organization` FK."""
    profile: Profile
    plans: Plans
    assumptions: Assumptions
    frame: ForecastFrame
    result: ProjectionResult
