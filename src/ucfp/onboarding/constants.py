"""Reserved identity and paths for the read-only sample household (see the seed/dump commands).

The sample organization and its scenario carry fixed UUIDs so the seed recreates them stably and the org
is identifiable across instances (e.g. #198 auto-joins members to it by UUID). The scenario's FKs reach
its Plans and Assumptions, so only these two ids are reserved; the Profile is the org's latest.
"""
import uuid
from pathlib import Path

SAMPLE_ORGANIZATION_UUID = uuid.UUID( '4b3ffa67-d602-4f61-bd11-5966c022bb90' )
SAMPLE_SCENARIO_UUID     = uuid.UUID( '0594ee18-a55a-49fd-af91-13558fe8276e' )

SAMPLE_ORGANIZATION_NAME = 'Sample Household'
SAMPLE_SCENARIO_NAME     = 'Sample Scenario'
SAMPLE_PLANS_NAME        = 'Sample Plans'
SAMPLE_ASSUMPTIONS_NAME  = 'Sample Assumptions'

# The committed plaintext fixture the seed reads and the dump writes.
SAMPLE_FIXTURE_PATH = Path( __file__ ).resolve().parent / 'fixtures' / 'sample_org.json'
