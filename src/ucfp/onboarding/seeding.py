"""Seed the read-only sample household from the committed fixture, and generate its forecast.

Reusable (a thin management command wraps it), idempotent, and portable: the fixture is plaintext, so the
encrypted `data` fields re-encrypt under the *local* key on save. The sample org and scenario carry the
reserved UUIDs (`constants`), so the org is stably identifiable (members are auto-joined to it by UUID).

Idempotency is *content-aware*: a re-seed refreshes the data (and re-runs the forecast, replacing the old
one) exactly when the committed fixture differs from what is stored -- the signal that an admin dumped an
edited sample. An unchanged fixture is a no-op, so the deploy entrypoint can run this on every start. We
compare the stored records against the fixture payloads directly (`data` + `acknowledged_sections`): that
catches *any* edit -- structural, value, or review-state -- whereas the Explore diff routines summarise
only value dials. A re-seed always preserves the org and its memberships; `force` refreshes unconditionally
(e.g. to re-run after an engine change with an unchanged fixture). The forecast runs outside the record
transaction (it can take seconds -- no reason to hold a write lock).
"""
import json
from dataclasses import dataclass
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from organization.enums import OrganizationRole
from organization.models import Organization, OrganizationMember

from ucfp.accounts.models import BooksOfAccountRecord
from ucfp.inputs.enums import UsageRole
from ucfp.inputs.models import (
    AssumptionsRecord, PlansRecord, ProfileRecord, ScenarioExploration, ScenarioRecord )
from ucfp.inputs.profile.repository import latest_profile, load_profile
from ucfp.inputs.scenarios.repository import load_scenario
from ucfp.planning.enums import PlanningFeature
from ucfp.planning.forms import GRANULARITY, default_forecast_duration_years, resolve_frame
from ucfp.planning.models import PlanningResultRecord, ProjectionRunRecord
from ucfp.planning.orchestration import run_and_capture

from ucfp.onboarding.constants import (
    SAMPLE_ASSUMPTIONS_NAME, SAMPLE_FIXTURE_PATH, SAMPLE_FORECAST_NAME, SAMPLE_ORGANIZATION_NAME,
    SAMPLE_ORGANIZATION_UUID, SAMPLE_PLANS_NAME, SAMPLE_SCENARIO_NAME, SAMPLE_SCENARIO_UUID )


class NoSuperuserError( Exception ):
    """No superuser exists to own the sample household -- `bootstrap` must run before this seed."""


@dataclass( frozen = True )
class SampleOrgResult:
    organization : Organization
    action       : str                                   # 'created' | 'refreshed' | 'preserved'


def seed_sample_org( force : bool = False ) -> SampleOrgResult:
    """Ensure the sample household exists (owned by the superuser) and holds a runnable scenario with a
    captured forecast. Content-aware idempotency: an already-seeded sample is refreshed only when the
    committed fixture differs from what is stored (or `force`); an unchanged fixture is left untouched. A
    refresh preserves the org and its memberships and replaces the captured forecast."""
    superuser = _superuser()
    with transaction.atomic():
        organization, _ = Organization.objects.get_or_create(
            uuid = SAMPLE_ORGANIZATION_UUID, defaults = { 'name': SAMPLE_ORGANIZATION_NAME } )
        OrganizationMember.objects.get_or_create(
            organization = organization, user = superuser,
            defaults = { 'organization_role': OrganizationRole.OWNER } )
        already_seeded = ScenarioRecord.objects.filter( uuid = SAMPLE_SCENARIO_UUID ).exists()
        if already_seeded and not force and _is_current( organization ):
            return SampleOrgResult( organization = organization, action = 'preserved' )
        if already_seeded:                                   # drops the old data + its 'Sample Forecast' run
            _clear_sample_data( organization )
        profile_record, scenario = _seed_records( organization )
    _generate_forecast( organization, profile_record, scenario )
    return SampleOrgResult(
        organization = organization, action = 'refreshed' if already_seeded else 'created' )


def _superuser():
    superuser = get_user_model().objects.filter( is_superuser = True ).order_by( 'pk' ).first()
    if superuser is None:
        raise NoSuperuserError( 'No superuser exists to own the sample household; run `bootstrap` first.' )
    return superuser


def _load_fixture():
    return json.loads( SAMPLE_FIXTURE_PATH.read_text() )


def _fixture_matches( organization ) -> bool:
    """Whether the org's seeded records already equal the committed fixture -- so a re-seed would change
    nothing. Compares only what the fixture carries (each record's `data` + `acknowledged_sections`); the
    Profile's `effective_date` is derived at seed time and deliberately excluded. A raw payload comparison
    (rather than the Explore value-diff) is intentional: it catches every kind of edit -- structural, value,
    or review-state."""
    scenario = ScenarioRecord.objects.filter( uuid = SAMPLE_SCENARIO_UUID ).first()
    profile  = latest_profile( organization )
    if ( scenario is None ) or ( profile is None ):
        return False
    fixture = _load_fixture()
    return ( _payload_matches( profile, fixture[ 'profile' ] )
             and _payload_matches( scenario.plans, fixture[ 'plans' ] )
             and _payload_matches( scenario.assumptions, fixture[ 'assumptions' ] ) )


def _payload_matches( record, payload ) -> bool:
    return ( record.data == payload[ 'data' ]
             and record.acknowledged_sections == payload[ 'acknowledged_sections' ] )


def _has_captured_forecast( organization ) -> bool:
    return PlanningResultRecord.objects.filter(
        organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST ).exists()


def _is_current( organization ) -> bool:
    """Whether the seeded sample is already up to date: its records equal the committed fixture *and* its
    forecast was captured. The forecast half lets a re-seed self-heal a run lost to a mid-seed forecast
    failure (the records commit before the forecast) -- which the fixture comparison alone would report as
    'preserved' indefinitely."""
    return _fixture_matches( organization ) and _has_captured_forecast( organization )


def _clear_sample_data( organization ):
    """Drop the sample org's data records (keeping the org and its memberships), most-referencing first,
    so a `force` re-seed starts clean."""
    PlanningResultRecord.objects.filter( organization = organization ).delete()
    ProjectionRunRecord.objects.filter( organization = organization ).delete()
    BooksOfAccountRecord.objects.filter( organization = organization ).delete()
    ScenarioExploration.objects.filter( organization = organization ).delete()
    ScenarioRecord.objects.filter( organization = organization ).delete()
    PlansRecord.objects.filter( organization = organization ).delete()
    AssumptionsRecord.objects.filter( organization = organization ).delete()
    ProfileRecord.objects.filter( organization = organization ).delete()


def _seed_records( organization ):
    """Create the SAVED Profile / Plans / Assumptions / Scenario from the fixture's plaintext payloads.
    Encrypted fields re-encrypt on save. The Profile starts on January 1 of the current year, so the run
    begins on a full-year boundary."""
    fixture = _load_fixture()
    effective = date( timezone.localdate().year, 1, 1 )

    profile_record = ProfileRecord.objects.create(
        organization = organization, effective_date = effective, label = effective.strftime( '%B %Y' ),
        data = fixture[ 'profile' ][ 'data' ],
        acknowledged_sections = fixture[ 'profile' ][ 'acknowledged_sections' ],
        usage_role = UsageRole.SAVED )
    plans_record = PlansRecord.objects.create(
        organization = organization, label = SAMPLE_PLANS_NAME, data = fixture[ 'plans' ][ 'data' ],
        acknowledged_sections = fixture[ 'plans' ][ 'acknowledged_sections' ], usage_role = UsageRole.SAVED )
    assumptions_record = AssumptionsRecord.objects.create(
        organization = organization, label = SAMPLE_ASSUMPTIONS_NAME,
        data = fixture[ 'assumptions' ][ 'data' ],
        acknowledged_sections = fixture[ 'assumptions' ][ 'acknowledged_sections' ],
        usage_role = UsageRole.SAVED )
    scenario = ScenarioRecord.objects.create(
        uuid = SAMPLE_SCENARIO_UUID, organization = organization, label = SAMPLE_SCENARIO_NAME,
        plans = plans_record, assumptions = assumptions_record, usage_role = UsageRole.SAVED )
    return profile_record, scenario


def _generate_forecast( organization, profile_record, scenario ):
    """Run and capture the Financial Forecast for the seeded scenario, outside the *record* transaction (it
    can take seconds) but within its own: the books, the `ProjectionRunRecord`, and its `PlanningResultRecord`
    commit together, so a mid-capture failure leaves nothing rather than a half-captured, invisible run. The
    horizon is the shared age-based default, so the sample spans the household's life."""
    profile = load_profile( profile_record )
    frame = resolve_frame(
        effective_date = profile_record.effective_date, start_choice = 'effective',
        duration_years = default_forecast_duration_years( profile, profile_record.effective_date ),
        granularity = GRANULARITY[ 'year' ] )
    scenario_inputs = load_scenario( scenario )
    with transaction.atomic():
        run = run_and_capture(
            organization = organization, profile = profile,
            plans = scenario_inputs.plans, assumptions = scenario_inputs.assumptions, frame = frame,
            label = SAMPLE_FORECAST_NAME, source_label = scenario.label )
        PlanningResultRecord.objects.create(
            organization = organization, feature = PlanningFeature.FINANCIAL_FORECAST,
            run = run, label = run.label )
