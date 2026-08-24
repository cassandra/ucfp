"""Dump an organization's latest Profile and a saved scenario's Plans/Assumptions to the example fixture.

The fixture is plaintext -- the encrypted `data` fields decrypt on ORM read -- so it re-encrypts under the
*local* key when seeded, and is portable across differently-keyed instances. Only a *complete* source is
dumped, so the seed always produces a runnable forecast. This is the refresh half of the live-edit loop:
the superuser hand-tunes the example household through the normal UI, then re-dumps to update the committed
fixture (no redeploy for content tweaks).
"""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from organization.models import Organization

from ucfp.inputs.scenarios.repository import scenarios_for
from ucfp.inputs.state import completed_profile
from ucfp.planning.gating import partition_scenarios

from ucfp.onboarding.constants import (
    EXAMPLE_FIXTURE_PATH, EXAMPLE_ORGANIZATION_NAME, EXAMPLE_ORGANIZATION_UUID, EXAMPLE_SCENARIO_UUID )


class Command( BaseCommand ):
    help = ( "Dump an organization's latest Profile and a saved scenario's Plans/Assumptions to the "
             "example-household fixture (decrypted plaintext). Refuses an incomplete source." )

    def add_arguments( self, parser ):
        parser.add_argument( '--org', help = 'Organization uuid or name (default: the example household).' )
        parser.add_argument( '--scenario', help = "Scenario uuid (default: the example scenario, else the "
                                                  "organization's sole saved scenario)." )
        parser.add_argument( '--output', help = f'Fixture path (default: {EXAMPLE_FIXTURE_PATH}).' )

    def handle( self, *args, **options ):
        organization = _resolve_organization( options[ 'org' ] )
        scenario     = _resolve_scenario( organization, options[ 'scenario' ] )
        profile      = _require_runnable( organization, scenario )
        payload      = _payload( profile, scenario )
        path         = options[ 'output' ] or str( EXAMPLE_FIXTURE_PATH )
        with open( path, 'w' ) as fixture:
            json.dump( payload, fixture, indent = 2, sort_keys = True )
            fixture.write( '\n' )
        if options[ 'verbosity' ] >= 1:
            self.stdout.write( self.style.SUCCESS(
                f"Dumped '{organization.name}' scenario '{scenario.label}' to {path}" ) )


def _resolve_organization( identifier ) -> Organization:
    if identifier is None:
        organization = ( Organization.objects.filter( uuid = EXAMPLE_ORGANIZATION_UUID ).first()
                         or Organization.objects.filter( name = EXAMPLE_ORGANIZATION_NAME ).first() )
        if organization is None:
            raise CommandError( 'No example household found; pass --org.' )
        return organization
    organization = _by_uuid_or_name( identifier )
    if organization is None:
        raise CommandError( f'No organization matching {identifier!r}.' )
    return organization


def _by_uuid_or_name( identifier ) -> Organization:
    try:
        return Organization.objects.filter( uuid = uuid.UUID( identifier ) ).first()
    except ValueError:                                     # not a uuid -- match by name
        return Organization.objects.filter( name = identifier ).first()


def _resolve_scenario( organization, identifier ):
    if identifier is not None:
        scenario = scenarios_for( organization ).filter( uuid = identifier ).first()
        if scenario is None:
            raise CommandError( f'No saved scenario {identifier!r} in {organization.name!r}.' )
        return scenario
    reserved = scenarios_for( organization ).filter( uuid = EXAMPLE_SCENARIO_UUID ).first()
    if reserved is not None:
        return reserved
    saved = list( scenarios_for( organization ) )
    if len( saved ) != 1:
        raise CommandError(
            f"{organization.name!r} has {len( saved )} saved scenarios; pass --scenario." )
    return saved[ 0 ]


def _require_runnable( organization, scenario ):
    """The org's completed profile -- raising unless it exists and `scenario` is runnable now -- so the
    fixture always seeds a working forecast."""
    profile = completed_profile( organization )
    if profile is None:
        raise CommandError(
            f"{organization.name!r} has no completed profile; complete it before dumping." )
    complete, _drift_blocked, _in_progress = partition_scenarios( organization, profile )
    if scenario.pk not in { runnable.pk for runnable in complete }:
        raise CommandError(
            f"Scenario {scenario.label!r} is not runnable (incomplete or drift-blocked); "
            'complete it before dumping.' )
    return profile


def _payload( profile, scenario ) -> dict:
    return {
        'profile'     : _record_payload( profile ),
        'plans'       : _record_payload( scenario.plans ),
        'assumptions' : _record_payload( scenario.assumptions ),
    }


def _record_payload( record ) -> dict:
    # `data` is already decrypted on read; `acknowledged_sections` carries the review/completeness state.
    return { 'data': record.data, 'acknowledged_sections': record.acknowledged_sections }
