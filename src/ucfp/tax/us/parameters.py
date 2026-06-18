"""US federal tax parameters -- the projectable VALUES (the engine supplies the
structure and logic).

A `TaxParameters` is a single tax year's figures. The Scenario projects a per-year
trajectory from a current-year baseline (`federal_2025`) -- indexing thresholds for
inflation, or applying a deliberate what-if such as a rate hike -- and constructs
the per-period `USFederalTaxEngine` with that year's parameters. The Period never
sees these; it treats tax as a black box.

NOTE: the core needed for the worked example (brackets, standard deduction, SS
thresholds). NIIT, ACA, the §1250/collectibles rates, and the capital-loss cap are
added as the engine's later stages land.
"""
from dataclasses import dataclass
from decimal import Decimal

from ucfp.tax.brackets import BracketTable

from .enums import FilingStatus


@dataclass( frozen = True )
class StandardDeduction:
    """Standard deduction: a base plus a per-qualifying-subject age-65 bonus and
    senior bonus (each added once for every subject who is 65+, so MFJ with both
    spouses 65+ gets two of each). The age-65 bonus is the traditional additional
    standard deduction; the senior bonus is the newer senior deduction, which phases
    out linearly across [phaseout_start, phaseout_end] of AGI (the age-65 bonus does
    not phase out)."""

    base           : Decimal
    age_65_bonus   : Decimal
    senior_bonus   : Decimal
    phaseout_start : Decimal
    phaseout_end   : Decimal


@dataclass( frozen = True )
class SocialSecurityThresholds:
    """Provisional-income thresholds for the SS taxability worksheet (the base and
    additional tiers). The 0.50 / 0.85 inclusion fractions are structural to the
    engine, not projected."""

    base       : Decimal
    additional : Decimal


@dataclass( frozen = True )
class ItemizedRules:
    """Floors and caps applied when totalling itemized deductions: the medical-
    expense AGI floor (only the excess is deductible), the SALT cap (state/local
    income + property tax), and the charitable AGI ceiling (cash-gift limit)."""

    medical_floor_rate   : Decimal
    salt_cap             : Decimal
    charitable_agi_limit : Decimal


@dataclass( frozen = True )
class FICARules:
    """Employee payroll-tax rates and bounds: Social Security (capped per worker at
    the wage base), Medicare (uncapped), and the Additional Medicare surtax on
    combined wages over the filing-status threshold."""

    ss_wage_base                   : Decimal
    ss_rate                        : Decimal
    medicare_rate                  : Decimal
    additional_medicare_rate       : Decimal
    additional_medicare_thresholds : dict


@dataclass( frozen = True )
class TaxParameters:
    """One tax year's US federal parameters, keyed by FilingStatus where they
    differ. Projectable per year by the Scenario."""

    ordinary_brackets       : dict
    ltcg_brackets           : dict
    standard_deduction      : dict
    ss_thresholds           : dict
    itemized_rules          : ItemizedRules
    capital_loss_offset_cap : Decimal
    section_1250_rate       : Decimal
    collectibles_rate       : Decimal
    niit_thresholds         : dict
    niit_rate               : Decimal
    fica_rules              : FICARules


def federal_2025() -> TaxParameters:
    """The 2025 current-year baseline -- the ground truth the Scenario projects from."""
    d = Decimal
    return TaxParameters(
        ordinary_brackets = {
            FilingStatus.MARRIED_JOINT : BracketTable( (
                ( d( '0' ), d( '0.10' ) ),
                ( d( '23850' ), d( '0.12' ) ),
                ( d( '96950' ), d( '0.22' ) ),
                ( d( '206700' ), d( '0.24' ) ),
                ( d( '394600' ), d( '0.32' ) ),
                ( d( '501050' ), d( '0.35' ) ),
                ( d( '751600' ), d( '0.37' ) ),
            ) ),
            FilingStatus.SINGLE : BracketTable( (
                ( d( '0' ), d( '0.10' ) ),
                ( d( '11925' ), d( '0.12' ) ),
                ( d( '48475' ), d( '0.22' ) ),
                ( d( '103350' ), d( '0.24' ) ),
                ( d( '197300' ), d( '0.32' ) ),
                ( d( '250525' ), d( '0.35' ) ),
                ( d( '626350' ), d( '0.37' ) ),
            ) ),
        },
        ltcg_brackets = {
            FilingStatus.MARRIED_JOINT : BracketTable( (
                ( d( '0' ), d( '0' ) ),
                ( d( '96700' ), d( '0.15' ) ),
                ( d( '600050' ), d( '0.20' ) ),
            ) ),
            FilingStatus.SINGLE : BracketTable( (
                ( d( '0' ), d( '0' ) ),
                ( d( '48350' ), d( '0.15' ) ),
                ( d( '533400' ), d( '0.20' ) ),
            ) ),
        },
        standard_deduction = {
            FilingStatus.MARRIED_JOINT : StandardDeduction(
                d( '31500' ), d( '1600' ), d( '6000' ), d( '150000' ), d( '250000' ) ),
            FilingStatus.SINGLE : StandardDeduction(
                d( '15750' ), d( '2000' ), d( '6000' ), d( '150000' ), d( '250000' ) ),
        },
        ss_thresholds = {
            FilingStatus.MARRIED_JOINT : SocialSecurityThresholds( d( '32000' ), d( '44000' ) ),
            FilingStatus.SINGLE : SocialSecurityThresholds( d( '25000' ), d( '34000' ) ),
        },
        # SALT cap is the canonical $10,000; the temporary OBBBA $40,000 cap (with its
        # high-income phasedown) is a refinement to set here when wanted.
        itemized_rules = ItemizedRules(
            medical_floor_rate   = d( '0.075' ),
            salt_cap             = d( '10000' ),
            charitable_agi_limit = d( '0.60' ),
        ),
        capital_loss_offset_cap = d( '3000' ),
        section_1250_rate = d( '0.25' ),
        collectibles_rate = d( '0.28' ),
        niit_thresholds = {
            FilingStatus.MARRIED_JOINT : d( '250000' ),
            FilingStatus.SINGLE : d( '200000' ),
        },
        niit_rate = d( '0.038' ),
        fica_rules = FICARules(
            ss_wage_base             = d( '176100' ),
            ss_rate                  = d( '0.062' ),
            medicare_rate            = d( '0.0145' ),
            additional_medicare_rate = d( '0.009' ),
            additional_medicare_thresholds = {
                FilingStatus.MARRIED_JOINT : d( '250000' ),
                FilingStatus.SINGLE : d( '200000' ),
            },
        ),
    )
