"""Reserved identity and paths for the read-only example household (see the seed/dump commands).

The example organization and its scenario carry fixed UUIDs so the seed recreates them stably and the org
is identifiable across instances (members are auto-joined to it by UUID). The scenario's FKs reach
its Plans and Assumptions, so only these two ids are reserved; the Profile is the org's latest.
"""
import uuid
from pathlib import Path

EXAMPLE_ORGANIZATION_UUID = uuid.UUID( '4b3ffa67-d602-4f61-bd11-5966c022bb90' )
EXAMPLE_SCENARIO_UUID     = uuid.UUID( '0594ee18-a55a-49fd-af91-13558fe8276e' )

EXAMPLE_ORGANIZATION_NAME = 'Example Household'
EXAMPLE_SCENARIO_NAME     = 'Example Scenario'
EXAMPLE_PLANS_NAME        = 'Example Plans'
EXAMPLE_ASSUMPTIONS_NAME  = 'Example Assumptions'
EXAMPLE_FORECAST_NAME     = 'Example Forecast'   # the captured run's title (scenario stays its provenance)

# The committed plaintext fixture the seed reads and the dump writes.
EXAMPLE_FIXTURE_PATH = Path( __file__ ).resolve().parent / 'fixtures' / 'example_org.json'
