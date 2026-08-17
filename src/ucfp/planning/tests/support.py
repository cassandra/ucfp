"""Shared fixtures for planning tests that need a real captured run.

A genuine run needs a runnable profile (with the always-seeded $0 Stocks/Bonds accounts the default
drawdown policy sweeps into), the seeded economic assumptions, and a frame. Several tests want exactly
this trio, so it lives here rather than being copied. Tests using these must `call_command(
'seed_parameter_sets' )` first, since `expected_assumptions` reads a seeded outlook.
"""
from datetime import date
from decimal import Decimal

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.assumptions.schemas import Assumptions
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Profile, SubjectProfile
from ucfp.jurisdiction.enums import FilingStatus, StatuteForecastType
from ucfp.jurisdiction.law import TaxProjection
from ucfp.parameter_sets.enums import EconomicOutlookVariant
from ucfp.parameter_sets.repository import economic_parameters
from ucfp.planning.materialization import ForecastFrame


def forecast_profile() -> Profile:
    """A runnable profile: cash plus the $0 Stocks/Bonds sweep homes the default drawdown policy needs."""
    return Profile(
        subjects = [ SubjectProfile( handle = 'subject', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE,
        home_tenure = HousingTenure.NEITHER,       # an explicit housing choice, so the profile is complete
        assets = [
            AssetProfile(
                handle = 'cash', name = 'Cash', asset_class = AssetClass.CASH,
                opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) ),
            AssetProfile(
                handle = 'stocks', name = 'Stocks', asset_class = AssetClass.STOCKS,
                opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ),
            AssetProfile(
                handle = 'bonds', name = 'Bonds', asset_class = AssetClass.BONDS,
                opening_value = Decimal( '0' ), cost_basis = Decimal( '0' ) ) ] )


def expected_assumptions() -> Assumptions:
    """Assumptions with the seeded EXPECTED economic outlook and current-law taxes -- enough to project."""
    return Assumptions(
        economics = economic_parameters( EconomicOutlookVariant.EXPECTED.label ),
        tax_projection = TaxProjection( forecast_type = StatuteForecastType.CURRENT_LAW ) )


def forecast_frame() -> ForecastFrame:
    """A short yearly frame (2026-2030) -- small enough to run fast in tests."""
    return ForecastFrame(
        start_date = date( 2026, 1, 1 ), end_date = date( 2030, 12, 31 ),
        granularity = Duration( 1, TimeUnit.YEAR ) )
