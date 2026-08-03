"""US federal tax parameters -- the projectable VALUES (the engine supplies the
structure and logic).

A `TaxParameters` is a single tax year's figures. The Scenario projects a per-year
trajectory from a current-year baseline (`federal_2026`) -- indexing thresholds for
inflation, or applying a deliberate what-if such as a rate hike -- and constructs
the per-period `USFederalTaxEngine` with that year's parameters. The Period never
sees these; it treats tax as a black box.
"""
from dataclasses import dataclass, replace
from decimal import Decimal

from ucfp.jurisdiction.brackets import BracketTable

from ucfp.jurisdiction.enums import FilingStatus


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

    def indexed( self, factor : Decimal ) -> 'StandardDeduction':
        """This deduction with all its dollar figures scaled by the cumulative COLA `factor`."""
        return replace(
            self,
            base           = self.base * factor,
            age_65_bonus   = self.age_65_bonus * factor,
            senior_bonus   = self.senior_bonus * factor,
            phaseout_start = self.phaseout_start * factor,
            phaseout_end   = self.phaseout_end * factor )


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
    additional_medicare_thresholds : dict[ FilingStatus, Decimal ]

    def indexed( self, factor : Decimal ) -> 'FICARules':
        """These rules with the Social Security wage base scaled by the cumulative COLA `factor`;
        the rates and the statutory (non-indexed) Additional Medicare thresholds are unchanged."""
        return replace( self, ss_wage_base = self.ss_wage_base * factor )


@dataclass( frozen = True )
class AcaParameters:
    """ACA premium-tax-credit parameters: the federal poverty guideline (first person
    plus each additional) and the applicable-percentage curve -- the share of income a
    household is expected to contribute toward premiums, zero below
    `applicable_lower_ratio` x the poverty line and rising at `applicable_slope` per
    unit of poverty-ratio up to `applicable_max_rate`. `applicable_upper_ratio` is the
    eligibility cliff: above it (reverted post-2025 law, 400% FPL) no credit is available."""

    poverty_first_person      : Decimal
    poverty_additional_person : Decimal
    applicable_lower_ratio    : Decimal
    applicable_slope          : Decimal
    applicable_max_rate       : Decimal
    applicable_upper_ratio    : Decimal

    def poverty_line( self, household_size : int ) -> Decimal:
        """The federal poverty guideline for a household of `household_size`."""
        return self.poverty_first_person + self.poverty_additional_person * ( household_size - 1 )

    def indexed( self, factor : Decimal ) -> 'AcaParameters':
        """These parameters with the federal poverty guideline figures scaled by the cumulative
        COLA `factor`; the applicable-percentage curve (ratios and rates) is unchanged."""
        return replace(
            self,
            poverty_first_person      = self.poverty_first_person * factor,
            poverty_additional_person = self.poverty_additional_person * factor )


@dataclass( frozen = True )
class PassiveActivityRules:
    """The active-participation special allowance for rental real-estate losses against
    ordinary income, phased out linearly across [phaseout_start, phaseout_end] of MAGI
    (full below the start, zero at/above the end). The excess loss is suspended."""

    loss_allowance : Decimal
    phaseout_start : Decimal
    phaseout_end   : Decimal


@dataclass( frozen = True )
class ContributionLimits:
    """Annual employee retirement-contribution limits: the employer-plan elective-deferral limit
    (401(k)/403(b)) and the personal-account limit (IRA, shared across traditional and Roth), each
    with a catch-up that applies once the owner reaches `catch_up_age`. An employer match is not an
    employee contribution and is not limited here (its separate overall cap is deferred)."""

    elective_deferral          : Decimal
    elective_deferral_catch_up : Decimal
    ira                        : Decimal
    ira_catch_up               : Decimal
    catch_up_age               : int

    def indexed( self, factor : Decimal ) -> 'ContributionLimits':
        """These limits with their dollar figures scaled by the cumulative COLA `factor`; the
        catch-up age is statutory, not indexed."""
        return replace(
            self,
            elective_deferral          = self.elective_deferral * factor,
            elective_deferral_catch_up = self.elective_deferral_catch_up * factor,
            ira                        = self.ira * factor,
            ira_catch_up               = self.ira_catch_up * factor )


@dataclass( frozen = True )
class TaxParameters:
    """One tax year's US federal parameters, keyed by FilingStatus where they
    differ. Projectable per year by the Scenario."""

    ordinary_brackets       : dict[ FilingStatus, BracketTable ]
    ltcg_brackets           : dict[ FilingStatus, BracketTable ]
    standard_deduction      : dict[ FilingStatus, StandardDeduction ]
    ss_thresholds           : dict[ FilingStatus, SocialSecurityThresholds ]
    itemized_rules          : ItemizedRules
    capital_loss_offset_cap : Decimal
    section_121_exclusion   : dict[ FilingStatus, Decimal ]
    section_1250_rate       : Decimal
    collectibles_rate       : Decimal
    niit_thresholds         : dict[ FilingStatus, Decimal ]
    niit_rate               : Decimal
    early_withdrawal_rate   : Decimal
    early_withdrawal_age    : Decimal
    contribution_limits     : ContributionLimits
    fica_rules              : FICARules
    aca                     : AcaParameters
    passive_activity        : PassiveActivityRules

    def indexed( self, factor : Decimal ) -> 'TaxParameters':
        """This baseline projected forward by a cumulative COLA `factor`: the inflation-indexed
        figures scale; the statutorily fixed ones stay put (so they bite harder over time, which
        is the real effect). INDEXED: the ordinary and LTCG brackets, the standard deduction, the
        retirement contribution limits, the Social Security wage base, and the ACA poverty
        guideline. NOT INDEXED (fixed in statute): the SS benefit-taxability thresholds, the NIIT
        and Additional Medicare thresholds, the capital-loss offset cap, the section 121 home-sale
        exclusion, the SALT cap, and the passive-activity allowance -- and every rate, ratio, and
        age."""
        return replace(
            self,
            ordinary_brackets   = { status : table.indexed( factor )
                                    for status, table in self.ordinary_brackets.items() },
            ltcg_brackets       = { status : table.indexed( factor )
                                    for status, table in self.ltcg_brackets.items() },
            standard_deduction  = { status : deduction.indexed( factor )
                                    for status, deduction in self.standard_deduction.items() },
            contribution_limits = self.contribution_limits.indexed( factor ),
            fica_rules          = self.fica_rules.indexed( factor ),
            aca                 = self.aca.indexed( factor ) )


# The year `federal_2026` describes -- the baseline a COLA projection indexes forward from.
BASE_YEAR = 2026


def federal_2026() -> TaxParameters:
    """The 2026 current-year baseline -- the ground truth the Scenario projects from."""
    d = Decimal
    return TaxParameters(
        ordinary_brackets = {
            FilingStatus.MARRIED_JOINT : BracketTable( (
                ( d( '0' ), d( '0.10' ) ),
                ( d( '24800' ), d( '0.12' ) ),
                ( d( '100800' ), d( '0.22' ) ),
                ( d( '211400' ), d( '0.24' ) ),
                ( d( '403550' ), d( '0.32' ) ),
                ( d( '512450' ), d( '0.35' ) ),
                ( d( '768700' ), d( '0.37' ) ),
            ) ),
            FilingStatus.SINGLE : BracketTable( (
                ( d( '0' ), d( '0.10' ) ),
                ( d( '12400' ), d( '0.12' ) ),
                ( d( '50400' ), d( '0.22' ) ),
                ( d( '105700' ), d( '0.24' ) ),
                ( d( '201775' ), d( '0.32' ) ),
                ( d( '256225' ), d( '0.35' ) ),
                ( d( '640600' ), d( '0.37' ) ),
            ) ),
        },
        ltcg_brackets = {
            FilingStatus.MARRIED_JOINT : BracketTable( (
                ( d( '0' ), d( '0' ) ),
                ( d( '98900' ), d( '0.15' ) ),
                ( d( '613700' ), d( '0.20' ) ),
            ) ),
            FilingStatus.SINGLE : BracketTable( (
                ( d( '0' ), d( '0' ) ),
                ( d( '49450' ), d( '0.15' ) ),
                ( d( '545500' ), d( '0.20' ) ),
            ) ),
        },
        standard_deduction = {
            FilingStatus.MARRIED_JOINT : StandardDeduction(
                d( '32200' ), d( '1650' ), d( '6000' ), d( '150000' ), d( '250000' ) ),
            FilingStatus.SINGLE : StandardDeduction(
                d( '16100' ), d( '2050' ), d( '6000' ), d( '75000' ), d( '175000' ) ),
        },
        ss_thresholds = {
            FilingStatus.MARRIED_JOINT : SocialSecurityThresholds( d( '32000' ), d( '44000' ) ),
            FilingStatus.SINGLE : SocialSecurityThresholds( d( '25000' ), d( '34000' ) ),
        },
        # SALT cap is the temporary OBBBA amount, $40,400 for 2026 (indexed 1% a year from the
        # $40,000 2025 base). Its high-income phasedown -- reduce by 30% of MAGI over $505,000,
        # floored at $10,000 -- is not modeled; the flat cap here is the no-phasedown case.
        itemized_rules = ItemizedRules(
            medical_floor_rate   = d( '0.075' ),
            salt_cap             = d( '40400' ),
            charitable_agi_limit = d( '0.60' ),
        ),
        capital_loss_offset_cap = d( '3000' ),
        section_121_exclusion = {
            FilingStatus.MARRIED_JOINT : d( '500000' ),
            FilingStatus.SINGLE : d( '250000' ),
        },
        section_1250_rate = d( '0.25' ),
        collectibles_rate = d( '0.28' ),
        niit_thresholds = {
            FilingStatus.MARRIED_JOINT : d( '250000' ),
            FilingStatus.SINGLE : d( '200000' ),
        },
        niit_rate = d( '0.038' ),
        # 10% additional tax on early retirement distributions before age 59-1/2; with
        # integer year-end ages the half-year reads as "under 59.5", i.e. age <= 59.
        early_withdrawal_rate = d( '0.10' ),
        early_withdrawal_age  = d( '59.5' ),
        # 2026 employee limits: 401(k) elective deferral $24,500 (+$8,000 catch-up at 50+);
        # IRA $7,500 (+$1,100 catch-up at 50+). The higher ages-60-63 catch-up is not modeled.
        contribution_limits = ContributionLimits(
            elective_deferral          = d( '24500' ),
            elective_deferral_catch_up = d( '8000' ),
            ira                        = d( '7500' ),
            ira_catch_up               = d( '1100' ),
            catch_up_age               = 50,
        ),
        fica_rules = FICARules(
            ss_wage_base             = d( '184500' ),
            ss_rate                  = d( '0.062' ),
            medicare_rate            = d( '0.0145' ),
            additional_medicare_rate = d( '0.009' ),
            additional_medicare_thresholds = {
                FilingStatus.MARRIED_JOINT : d( '250000' ),
                FilingStatus.SINGLE : d( '200000' ),
            },
        ),
        # 2026 reverts to the ORIGINAL (pre-ARPA) ACA structure: the enhanced IRA/ARPA subsidies
        # expired after 2025. The applicable-percentage curve rises to a 9.96% cap (Rev. Proc.
        # 2025-25), steeper than the 8.5% enhanced cap, and a hard 400%-of-FPL eligibility cliff
        # returns. Poverty figures are the 2025 HHS guidelines (48 states) used for 2026 coverage:
        # $15,650 first person, +$5,500 each additional. The curve here is the best linear fit of
        # the piecewise 2026 table (passing through 4.19% at 150% FPL and the 9.96% cap at 300%
        # FPL); its lower ratio is the line's x-intercept, not a real FPL threshold. NOTE: the hard
        aca = AcaParameters(
            poverty_first_person      = d( '15650' ),
            poverty_additional_person = d( '5500' ),
            applicable_lower_ratio    = d( '0.41' ),
            applicable_slope          = d( '0.0385' ),
            applicable_max_rate       = d( '0.0996' ),
            applicable_upper_ratio    = d( '4.0' ),
        ),
        passive_activity = PassiveActivityRules(
            loss_allowance = d( '25000' ),
            phaseout_start = d( '100000' ),
            phaseout_end   = d( '150000' ),
        ),
    )
