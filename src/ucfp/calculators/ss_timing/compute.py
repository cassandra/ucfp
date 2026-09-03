"""Social Security claiming-strategy comparison: sweep the age-62..70 claiming grid and rank the
strategies by lifetime benefit, via the forecast engine.

The couple-aware benefit -- each person's own, the lower earner's spousal top-up once both collect,
and the survivor step-up after a death -- lives in the engine
(`jurisdiction.social_security_household`, invoked per period). This module is the specialized,
Social-Security-only materialization above it: from a household's claiming facts it builds a
stripped `ForecastParameters` (subjects + Social Security entitlements + expected-lifetime removals +
the economic outlook), runs one forecast per claiming combination, and reduces each run's booked
Social Security to a lifetime total -- the nominal ("raw") sum, its present value, and its effective value.

Every strategy runs over one shared horizon -- from the earliest age-62 claim in the household to the
last expected death -- so early claiming's extra years and late claiming's larger checks are weighed
on equal footing. Each year's benefit is discounted two ways to the start (age-62) year, shared by every
strategy: `present_value` at inflation (the app's "today's dollars" convention), and `effective_value` at
the visitor's expected asset return -- which additionally prices in the opportunity cost of deferring
(money drawn from savings to bridge the wait forfeits its compounding). Strategies are ranked by effective
value; the two coincide when no return above inflation is set.

For the results drill-in, `strategy_year_details` apportions each year's engine household total into the
members' own / spousal / survivor parts. Because the COLA and reduction scale the whole benefit uniformly,
the parts' ratios are overlay-free: the split comes from the jurisdiction breakdown while the totals stay
the engine's -- so no economic overlay is reproduced here, and the per-person figures never read the books
(sidestepping the engine's account-retitling on a death).
"""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from itertools import product
from typing import Optional

from common.rate import FULL_RATE, Rate
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast, ForecastResult
from ucfp.forecast.parameters import (
    AssetParameters, ForecastParameters, SocialSecurityEntitlement, Subject, SubjectRemoval )
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.government_pension import GovernmentPension
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.jurisdiction.social_security_household import (
    HouseholdMember, MemberBenefit, household_benefit_breakdown )
from ucfp.jurisdiction.us.mortality import Sex, alive_fraction, life_expectancy


EARLIEST_CLAIM_AGE = 62
LATEST_CLAIM_AGE   = 70
CLAIM_AGES         = tuple( range( EARLIEST_CLAIM_AGE, LATEST_CLAIM_AGE + 1 ) )

# The actuarial horizon cap: the age each claimant's survival curve is projected through in the
# mortality-weighted basis. Survival past ~100 is slight and the weighted benefit there rounds to nothing,
# so the sweep stops here rather than running the curve to its 119 tail.
HORIZON_CAP_AGE = 100

# The default year the funding-shortfall reduction begins (see `Assumptions.benefits_payable`), when the
# visitor sets no other. The SSA trust-fund depletion is currently projected for the early 2030s.
_DEFAULT_REDUCTION_YEAR = 2032

_ONE = Decimal( '1' )

# The calculator is US-only (the FRA/PIA rules behind the benefit are the US ones); the facade is
# stateless, so a single instance serves the per-person breakdown split.
_GOVERNMENT_PENSION = GovernmentPension( JurisdictionType.US_FEDERAL )

# The Social Security COLA (tied to CPI-W) has historically trailed general inflation; rather than ask for
# both, the calculator takes one inflation figure and derives the COLA as inflation less this lag. A single
# familiar input, at the cost of a fixed assumed gap (see the results page's methodology note).
COLA_INFLATION_LAG = Rate( Decimal( '0.003' ) )


class LifeExpectancyBasis( Enum ):
    """How long each claimant is assumed to live, the household-level choice between the comparison's two
    paths. SPECIFIC treats each claimant's `expected_lifetime` as a fixed death age -- one engine run per
    strategy, the exact deterministic result. ACTUARIAL instead weights every future year's benefit by the
    probability the claimant is alive to receive it (from the SSA survival curves, per `Claimant.sex` and
    `Claimant.setback`) and reports the mortality-weighted expected value; `expected_lifetime` is unused."""

    SPECIFIC  = 'specific'
    ACTUARIAL = 'actuarial'


@dataclass( frozen = True )
class Claimant:
    """One person's Social Security facts for the comparison: their `name`, `birth_year`, monthly
    PIA (`pia_monthly` -- the benefit at full retirement age, in start-year dollars) and
    `expected_lifetime` -- the age through which they are assumed to live, after which their benefit
    ends (the SPECIFIC basis; None, and unused, under ACTUARIAL). `sex` and `setback` drive the ACTUARIAL
    basis instead: the survival curve to weight by, and a shift of the mortality lookup age in years
    (positive = frailer/shorter life, negative = healthier/longer) for a claimant who expects to differ
    from average. Birthdays are modeled on January 1, so a claiming age lands on an exact date."""

    name              : str
    birth_year        : int
    pia_monthly       : Decimal
    expected_lifetime : Optional[ int ] = None
    sex               : Optional[ Sex ] = None
    setback           : int             = 0

    @property
    def birthdate( self ) -> date:
        """The modeled birthdate -- January 1 of the birth year, so a claiming age is an exact age."""
        return date( self.birth_year, 1, 1 )


@dataclass( frozen = True )
class Assumptions:
    """The economic backdrop the comparison projects under: general `inflation` (the economic outlook the
    runs project under, and the fallback present-value discount), the Social Security `cola` (annual
    benefit growth), the funding-shortfall reduction -- `benefits_payable`, the retained share of
    scheduled benefits from `reduction_year` on (the full rate = no reduction, the default) -- and an
    optional `expected_return`, the visitor's expected nominal asset return, which when given becomes
    the present-value discount (see `discount_rate`)."""

    inflation        : Rate
    cola             : Rate
    benefits_payable : Rate           = FULL_RATE
    reduction_year   : int            = _DEFAULT_REDUCTION_YEAR
    expected_return  : Optional[ Rate ] = None

    @property
    def discount_rate( self ) -> Rate:
        """The nominal rate present value discounts at: the visitor's `expected_return` when given --
        pricing in the opportunity cost of deferring benefits (money left invested keeps compounding) --
        else `inflation`, the zero-real-opportunity-cost "today's dollars" view. The engine run itself
        always projects under `inflation`; this rate only weighs the resulting benefit stream."""
        return self.expected_return if self.expected_return is not None else self.inflation

    @classmethod
    def from_inflation( cls, inflation : Rate, benefits_payable : Rate = FULL_RATE,
                        reduction_year : int = _DEFAULT_REDUCTION_YEAR,
                        expected_return : Optional[ Rate ] = None ) -> 'Assumptions':
        """Assumptions from a single inflation figure: the SS COLA is derived as inflation less the
        historical lag (`COLA_INFLATION_LAG`), floored at zero, so the visitor sets one familiar number
        rather than two rates that co-vary. `expected_return`, when given, drives the present-value
        discount instead of inflation (the opportunity-cost view)."""
        cola = max( inflation.fraction - COLA_INFLATION_LAG.fraction, Decimal( '0' ) )
        return cls( inflation = inflation, cola = Rate( cola ), benefits_payable = benefits_payable,
                    reduction_year = reduction_year, expected_return = expected_return )


@dataclass( frozen = True )
class YearBenefit:
    """One year of a strategy: the household's total Social Security that year -- `nominal` (as paid,
    COLA-grown and shortfall-reduced), `present_value` (that year in today's dollars, discounted at
    inflation), and `effective_value` (discounted instead at the expected asset return, so it also carries
    the opportunity cost of deferring). The two discounts coincide when no return above inflation is set."""

    year            : int
    nominal         : Decimal
    present_value   : Decimal
    effective_value : Decimal


@dataclass( frozen = True )
class MemberYear:
    """One member's nominal Social Security in a year, split into its parts -- own, spousal, and survivor.
    Either the own(+spousal) pair or the survivor is non-zero (the survivor benefit replaces own and
    spousal at the first death)."""

    own      : Decimal
    spousal  : Decimal
    survivor : Decimal

    @property
    def total( self ) -> Decimal:
        return self.own + self.spousal + self.survivor


@dataclass( frozen = True )
class YearDetail:
    """One year of a strategy for the drill-in table: each member's nominal parts (aligned to the earners,
    higher first), each member's age, the `household` total with its `present_value` (today's dollars, at
    inflation) and `effective_value` (at the expected asset return), and `is_transition` -- the first-death
    year where the survivor benefit begins."""

    year            : int
    ages            : tuple[ int, ... ]
    members         : tuple[ MemberYear, ... ]
    household       : Decimal
    present_value   : Decimal
    effective_value : Decimal
    is_transition   : bool

    @property
    def survivor( self ) -> Decimal:
        """The survivor benefit that year (whichever member is the survivor; zero while both live)."""
        return sum( ( member.survivor for member in self.members ), Decimal( '0' ) )

    @property
    def ages_label( self ) -> str:
        """The household's ages that year -- '68' for one person, '68 & 66' for a couple."""
        return ' & '.join( str( age ) for age in self.ages )


@dataclass( frozen = True )
class Strategy:
    """One claiming combination and its lifetime outcome. `claim_ages` is the age each claimant
    files, ordered higher earner first (the heatmap's two axes for a couple; a single value for one
    person). `raw_total` is the nominal lifetime sum; `present_value` restates it in today's dollars
    (discounted at inflation); `effective_value` discounts instead at the expected asset return, pricing in
    the opportunity cost of deferring -- the figure strategies are ranked by. `year_benefits` is the
    year-by-year detail."""

    claim_ages      : tuple[ int, ... ]
    raw_total       : Decimal
    present_value   : Decimal
    effective_value : Decimal
    year_benefits   : tuple[ YearBenefit, ... ]


@dataclass( frozen = True )
class Comparison:
    """The full sweep: the `claimants` (higher earner first) and every `Strategy` over the 62..70
    grid (9 for one person or a single-earner couple, 81 for a dual-earner couple). `best` and `ranked` are
    derived so the heatmap and the ranked list read one settled result."""

    claimants  : tuple[ Claimant, ... ]
    strategies : tuple[ Strategy, ... ]

    @property
    def dimensions( self ) -> int:
        """How many claiming ages the sweep varies -- 1 for a single person or a single-earner couple (the
        1-D strip), 2 for a dual-earner couple (the 2-D grid). Read from a strategy's claim ages, so the
        heatmap and ranked list render the right shape regardless of the household size."""
        return len( self.strategies[ 0 ].claim_ages )

    @property
    def best( self ) -> Strategy:
        """The strategy with the greatest effective value -- the opportunity-cost-adjusted figure the
        results page marks as best (it equals the greatest present value when no return is set)."""
        return max( self.strategies, key = lambda strategy: strategy.effective_value )

    @property
    def ranked( self ) -> tuple[ Strategy, ... ]:
        """Strategies from best to worst by effective value -- the ranked-list order."""
        return tuple( sorted(
            self.strategies, key = lambda strategy: strategy.effective_value, reverse = True ) )


def earners_of( claimants : list[ Claimant ] ) -> tuple[ Claimant, ... ]:
    """`claimants` ordered higher earner first (by PIA) -- the single household orientation the whole
    comparison reads: the heatmap axes, the ranked and detail columns, and the spousal/survivor roles. A
    non-earning spouse (zero PIA) sorts last, so the deciding earners always lead the tuple."""
    return tuple( sorted( claimants, key = lambda claimant: claimant.pia_monthly, reverse = True ) )


def deciding_count( claimants : list[ Claimant ] ) -> int:
    """How many claiming ages the sweep varies -- one per earner with a positive PIA. A dual-earner couple
    decides two (the 2-D heatmap grid); a single person, or a couple with a non-earning spouse, decides one
    (the 1-D strip). The non-earning spouse is not swept: they claim their spousal benefit when the primary
    earner files (see `member_claims`), so the couple's decision stays one-dimensional."""
    return sum( 1 for claimant in claimants if claimant.pia_monthly > 0 )


@dataclass( frozen = True )
class MemberClaim:
    """One household member resolved for a claiming combination: the `claimant`, the `claiming_date` their
    benefit begins, and whether they are a deciding earner (`is_earner` -- a positive PIA, whose claim age
    the sweep varies) or a non-earning spouse (a zero PIA, who claims a spousal benefit when the primary
    earner files, so their claim is derived rather than swept)."""

    claimant      : Claimant
    claiming_date : date
    is_earner     : bool

    @property
    def claim_age( self ) -> int:
        """The claimant's age on their claiming date -- the swept age for an earner, the derived age (at the
        primary earner's filing) for a non-earning spouse."""
        return self.claiming_date.year - self.claimant.birth_year


def member_claims(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ] ) -> list[ MemberClaim ]:
    """Resolve each household member's claim for a swept combination. `earners` are PIA-ordered (higher
    first), so the deciding earners -- those with a positive PIA -- lead the tuple and align to `claim_ages`
    (one swept age each); a trailing non-earning spouse (zero PIA) is not swept and claims when the primary
    earner files (the calculator's same-time assumption -- a non-earning spouse gains nothing by waiting).
    The primary earner leads, so the household always has at least one deciding earner (the form and
    `compare_claiming_strategies` reject an all-zero household).

    Each member is classified an earner by their own PIA, and the swept ages are drawn in order for those
    earners -- the two agree only when `claim_ages` carries exactly one age per deciding earner, which the
    assertion pins so a mismatched-length call fails loudly rather than silently misclassifying a member."""
    assert len( claim_ages ) == deciding_count( earners ), (
        'member_claims expects one swept age per deciding earner (a positive PIA)' )
    primary_claiming = date( earners[ 0 ].birth_year + claim_ages[ 0 ], 1, 1 )
    swept_ages       = iter( claim_ages )
    claims           = list()
    for earner in earners:
        is_earner = bool( earner.pia_monthly > 0 )
        claiming  = ( date( earner.birth_year + next( swept_ages ), 1, 1 ) if is_earner
                      else primary_claiming )
        claims.append( MemberClaim( claimant = earner, claiming_date = claiming, is_earner = is_earner ) )
        continue
    return claims


def representative_claimants( claimants : list[ Claimant ] ) -> tuple[ Claimant, ... ]:
    """The earners (higher first) with `expected_lifetime` filled from each person's actuarial life
    expectancy -- their survival curve (sex + setback) read at the earliest-claim year. This turns an
    ACTUARIAL household into a single deterministic *representative* lifetime: the year-by-year detail runs
    to these ages (real income, a real survivor step-up) and the recap reports them, while the ranked
    heatmap keeps the full probabilistic expectation. On a claimant who already has an expected lifetime
    (the SPECIFIC path) this is unnecessary, but it recomputes from the tables regardless."""
    earners = earners_of( claimants )
    start   = min( earner.birth_year + EARLIEST_CLAIM_AGE for earner in earners )
    return tuple(
        replace( earner, expected_lifetime = _expected_death_age( earner, start ) )
        for earner in earners )


def _expected_death_age( claimant : Claimant, horizon_start_year : int ) -> int:
    """The claimant's expected age at death from the life table, conditioned on surviving to the household's
    earliest-claim year (the weighting's anchor) -- rounded to a whole age for the deterministic run."""
    current_age = horizon_start_year - claimant.birth_year
    return round( life_expectancy( current_age, claimant.sex, claimant.setback ) )


def compare_claiming_strategies(
        claimants : list[ Claimant ], assumptions : Assumptions,
        basis : LifeExpectancyBasis = LifeExpectancyBasis.SPECIFIC ) -> Comparison:
    """Sweep the 62..70 claiming grid for `claimants` (one person or a couple) and rank the
    strategies by lifetime effective value (present value adjusted for the opportunity cost of deferring).
    `basis` chooses how long each claimant lives: SPECIFIC uses their expected lifetime (one run per
    strategy), ACTUARIAL weights each year by survival (the mortality-weighted expected value). The
    couple's spousal and survivor benefits, the COLA, and the funding-shortfall reduction all come from the
    engine. Claimants are ordered by PIA (higher earner first), the orientation the results grid reads.

    The sweep varies one claim age per *deciding* earner (a positive PIA): 9 strategies for a single person,
    81 for a dual-earner couple, and 9 for a couple with a non-earning spouse -- whose spousal benefit is
    claimed when the primary earner files, collapsing the couple's decision to one dimension."""
    if not 1 <= len( claimants ) <= 2:
        raise ValueError(
            f'A Social Security comparison covers one person or a couple; got {len( claimants )}.' )
    dimensions = deciding_count( claimants )
    if dimensions == 0:
        raise ValueError( 'A Social Security comparison needs at least one earner with a positive PIA.' )
    earners      = earners_of( claimants )
    horizon      = _horizon_for( earners, basis )
    combinations = product( CLAIM_AGES, repeat = dimensions )
    strategies   = tuple(
        _strategy_for( earners, claim_ages, assumptions, horizon, basis )
        for claim_ages in combinations )
    return Comparison( claimants = earners, strategies = strategies )


def compute_strategy(
        claimants : list[ Claimant ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions,
        basis : LifeExpectancyBasis = LifeExpectancyBasis.SPECIFIC ) -> Strategy:
    """One strategy for a chosen claiming combination (the higher earner's age first) -- the results page's
    drill-in recompute, a single strategy rather than the whole sweep. `basis` matches the sweep's (see
    `compare_claiming_strategies`). Claimants are ordered by PIA, so `claim_ages` aligns to the heatmap's
    axes."""
    earners = earners_of( claimants )
    return _strategy_for( earners, claim_ages, assumptions, _horizon_for( earners, basis ), basis )


def strategy_year_details(
        earners : tuple[ Claimant, ... ], strategy : Strategy ) -> tuple[ YearDetail, ... ]:
    """The selected strategy's year-by-year table: each year's engine household total apportioned into the
    members' own / spousal / survivor parts. The COLA and funding reduction are uniform scalings, so the
    parts' ratios are overlay-free -- the split comes from the jurisdiction breakdown while the totals stay
    the engine's. `earners` are the comparison's claimants (higher earner first)."""
    members       = _household_members( earners, strategy.claim_ages )
    details       = list()
    seen_survivor = False
    for benefit in strategy.year_benefits:
        breakdown    = household_benefit_breakdown( members, _GOVERNMENT_PENSION, date( benefit.year, 1, 1 ) )
        today_total  = sum( ( part.total for part in breakdown.values() ), Decimal( '0' ) )
        member_years = tuple(
            _apportion( breakdown.get( _handle( index ) ), benefit.nominal, today_total )
            for index in range( len( members ) ) )
        has_survivor = any( member.survivor > 0 for member in member_years )
        details.append( YearDetail(
            year            = benefit.year,
            ages            = tuple( benefit.year - earner.birth_year for earner in earners ),
            members         = member_years,
            household       = benefit.nominal,
            present_value   = benefit.present_value,
            effective_value = benefit.effective_value,
            is_transition   = has_survivor and not seen_survivor ) )
        seen_survivor = seen_survivor or has_survivor
        continue
    return tuple( details )


def _household_members(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ] ) -> list[ HouseholdMember ]:
    """The jurisdiction calculator's members for this combination -- each earner claiming at their resolved
    date and leaving at their expected lifetime -- handles index-keyed to the earners (higher first), the
    same keys the forecast used, so the breakdown reads back in that order. A non-earning spouse carries no
    own PIA (None), so the calculator synthesizes their pure spousal benefit claimed on the primary's date."""
    return [
        HouseholdMember(
            subject_handle = _handle( index ),
            birthdate      = claim.claimant.birthdate,
            pia_monthly    = claim.claimant.pia_monthly if claim.is_earner else None,
            claiming_date  = claim.claiming_date,
            death_date     = date(
                claim.claimant.birth_year + claim.claimant.expected_lifetime, 1, 1 ) )
        for index, claim in enumerate( member_claims( earners, claim_ages ) ) ]


def _apportion( part : Optional[ MemberBenefit ], household_nominal : Decimal,
                today_total : Decimal ) -> MemberYear:
    """A member's nominal parts: their today's-dollars own/spousal/survivor scaled to the engine's nominal
    household total by their share of it. Empty when no benefit is paid that year (nothing to apportion)."""
    if part is None or today_total == 0:
        return MemberYear( Decimal( '0' ), Decimal( '0' ), Decimal( '0' ) )
    scale = household_nominal / today_total       # = COLA x reduction, carried by the engine's nominal total
    return MemberYear(
        own = part.own * scale, spousal = part.spousal * scale, survivor = part.survivor * scale )


@dataclass( frozen = True )
class _Horizon:
    """The shared projection span every strategy runs over: from the earliest age-62 claim in the
    household to the last expected death. One horizon keeps the strategies comparable -- early
    claiming's extra years and late claiming's larger checks are weighed against the same end."""

    start_year : int
    end_year   : int

    @classmethod
    def for_household( cls, claimants : tuple[ Claimant, ... ] ) -> '_Horizon':
        """The SPECIFIC-basis span: earliest age-62 claim to the last entered expected death."""
        start = min( claimant.birth_year + EARLIEST_CLAIM_AGE for claimant in claimants )
        end   = max( claimant.birth_year + claimant.expected_lifetime for claimant in claimants )
        return cls( start_year = start, end_year = end )

    @classmethod
    def actuarial( cls, claimants : tuple[ Claimant, ... ] ) -> '_Horizon':
        """The ACTUARIAL-basis span: earliest age-62 claim to the last claimant's age-100 cap -- long
        enough for the survival weights to taper to nothing without running the curve to its tail."""
        start = min( claimant.birth_year + EARLIEST_CLAIM_AGE for claimant in claimants )
        end   = max( claimant.birth_year + HORIZON_CAP_AGE for claimant in claimants )
        return cls( start_year = start, end_year = end )


def _horizon_for(
        claimants : tuple[ Claimant, ... ], basis : LifeExpectancyBasis ) -> _Horizon:
    """The projection span for the chosen basis -- the age-100 cap for ACTUARIAL, the entered expected
    lifetimes for SPECIFIC."""
    if basis is LifeExpectancyBasis.ACTUARIAL:
        return _Horizon.actuarial( claimants )
    return _Horizon.for_household( claimants )


def _strategy_for(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, horizon : _Horizon, basis : LifeExpectancyBasis ) -> Strategy:
    """One claiming combination on the chosen basis: the SPECIFIC single-run reduction, or the ACTUARIAL
    survival-weighted expected value."""
    if basis is LifeExpectancyBasis.ACTUARIAL:
        nominals = _actuarial_nominals( earners, claim_ages, assumptions, horizon )
    else:
        nominals = _specific_nominals( earners, claim_ages, assumptions, horizon )
    return _strategy_from_nominals( claim_ages, nominals, assumptions, horizon )


def _strategy_from_nominals(
        claim_ages : tuple[ int, ... ], nominals : list[ Decimal ],
        assumptions : Assumptions, horizon : _Horizon ) -> Strategy:
    """A `Strategy` from a per-year household nominal stream (deterministic or expected): discount each year
    two ways and sum to the lifetime nominal, present, and effective totals."""
    year_benefits   = _year_benefits( nominals, assumptions, horizon )
    raw_total       = sum( ( benefit.nominal for benefit in year_benefits ), Decimal( '0' ) )
    present_value   = sum( ( benefit.present_value for benefit in year_benefits ), Decimal( '0' ) )
    effective_value = sum( ( benefit.effective_value for benefit in year_benefits ), Decimal( '0' ) )
    return Strategy(
        claim_ages = claim_ages, raw_total = raw_total, present_value = present_value,
        effective_value = effective_value, year_benefits = year_benefits )


def _specific_nominals(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, horizon : _Horizon ) -> list[ Decimal ]:
    """The SPECIFIC basis: one engine run in which each claimant dies at their expected lifetime, reduced to
    the per-year household nominal -- the exact deterministic benefit stream."""
    deaths = [ claimant.birth_year + claimant.expected_lifetime for claimant in earners ]
    return _nominal_by_year( _run( earners, claim_ages, assumptions, deaths, horizon ), horizon )


def _actuarial_nominals(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, horizon : _Horizon ) -> list[ Decimal ]:
    """The ACTUARIAL basis: each year's *expected* household nominal, weighting the engine's benefit by the
    probability the household is in each survival state that year. One person is one run weighted by their
    own survival; a couple is three runs -- both alive, higher earner survives, lower earner survives --
    weighted by the (mid-year) joint survival probabilities, assuming independent lifetimes."""
    if len( earners ) == 1:
        return _weighted_single( earners[ 0 ], claim_ages, assumptions, horizon )
    return _weighted_couple( earners, claim_ages, assumptions, horizon )


def _weighted_single(
        claimant : Claimant, claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, horizon : _Horizon ) -> list[ Decimal ]:
    """A single claimant's expected nominal stream: the run in which they live the whole horizon, each
    year's benefit scaled by the expected fraction of that year they are alive to receive it."""
    alive = _nominal_by_year(
        _run( ( claimant, ), claim_ages, assumptions, [ None ], horizon ), horizon )
    return [ nominal * _claimant_alive_fraction( claimant, horizon.start_year + offset, horizon )
             for offset, nominal in enumerate( alive ) ]


def _weighted_couple(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, horizon : _Horizon ) -> list[ Decimal ]:
    """A couple's expected nominal stream from three survival-state runs. Each state is realized by placing
    the deceased's removal just before the horizon (so they are a survivor for every year), which the engine
    turns into the survivor step-up; the neither-alive state pays nothing. Per year the states are combined
    by their joint (mid-year) survival weights -- the linearity-of-expectation collapse of every death-year
    pairing into a per-year state weighting."""
    higher, lower = earners
    before_start  = horizon.start_year - 1                # a death here reads as gone for the whole horizon
    both   = _nominal_by_year(
        _run( earners, claim_ages, assumptions, [ None, None ], horizon ), horizon )
    higher_alone = _nominal_by_year(
        _run( earners, claim_ages, assumptions, [ None, before_start ], horizon ), horizon )
    lower_alone  = _nominal_by_year(
        _run( earners, claim_ages, assumptions, [ before_start, None ], horizon ), horizon )
    expected = list()
    for offset in range( len( both ) ):
        year       = horizon.start_year + offset
        higher_f   = _claimant_alive_fraction( higher, year, horizon )
        lower_f    = _claimant_alive_fraction( lower, year, horizon )
        expected.append(
            both[ offset ]         * ( higher_f * lower_f )
            + higher_alone[ offset ] * ( higher_f * ( _ONE - lower_f ) )
            + lower_alone[ offset ]  * ( lower_f * ( _ONE - higher_f ) ) )
        continue
    return expected


def _claimant_alive_fraction( claimant : Claimant, year : int, horizon : _Horizon ) -> Decimal:
    """The expected fraction of `year` the claimant is alive, conditioned on being alive at the horizon
    start (the earliest-claim year) -- the mid-year-of-death weight from their survival curve, per sex and
    setback."""
    current_age = horizon.start_year - claimant.birth_year
    year_age    = year - claimant.birth_year
    return alive_fraction( current_age, year_age, claimant.sex, claimant.setback )


def _run(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, deaths : list[ Optional[ int ] ],
        horizon : _Horizon ) -> ForecastResult:
    """Run one Social-Security-only forecast for a claiming combination with the given per-earner death
    years (None = lives the whole horizon)."""
    return Forecast( _forecast_parameters( earners, claim_ages, assumptions, deaths, horizon ) ).run()


def _forecast_parameters(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, deaths : list[ Optional[ int ] ],
        horizon : _Horizon ) -> ForecastParameters:
    """The stripped, Social-Security-only forecast for one claiming combination: a subject and SS
    entitlement per claimant (each earner claiming at their swept age), a subject removal for each claimant
    with a death year (None leaves them alive for the whole horizon), a single cash hub for the benefits to
    land in, and the economic outlook -- no other income, assets, or expenses, so only the Social Security
    lines carry value. A non-earning spouse gets an entitlement with no PIA, so the engine synthesizes their
    spousal benefit claimed on the primary earner's date rather than sweeping a claim age they do not have."""
    claims       = member_claims( earners, claim_ages )
    subjects     = [ Subject( claim.claimant.name, claim.claimant.birthdate, handle = _handle( index ) )
                     for index, claim in enumerate( claims ) ]
    entitlements = [
        SocialSecurityEntitlement(
            subject,
            claim.claimant.pia_monthly if claim.is_earner else None,
            claim.claiming_date if claim.is_earner else None )
        for subject, claim in zip( subjects, claims ) ]
    removals     = [
        SubjectRemoval( date( death, 1, 1 ), subject.handle )
        for subject, death in zip( subjects, deaths ) if death is not None ]
    return ForecastParameters(
        start_date       = date( horizon.start_year, 1, 1 ),
        end_date         = date( horizon.end_year, 12, 31 ),
        filing_status    = FilingStatus.MARRIED_JOINT if len( earners ) == 2 else FilingStatus.SINGLE,
        statute          = StatuteProfile(
            JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) ),
        subjects         = subjects,
        assets           = [ AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ) ) ],
        social_security  = entitlements,
        subject_removals = removals,
        # The comparison ranks by gross booked Social Security; taxation never changes that number, and
        # this stripped run has no wages, pre-tax accounts, or contributions -- so skip the tax layer
        # entirely. A sizeable per-run speed-up (the couple actuarial sweep is many runs), identical
        # results.
        skip_taxation    = True,
        economic_outlook = EconomicOutlook.constant( EconomicParameters(
            inflation                        = assumptions.inflation,
            social_security_cola             = assumptions.cola,
            social_security_benefits_payable = assumptions.benefits_payable,
            social_security_reduction_year   = assumptions.reduction_year ) ) )


def _handle( index : int ) -> str:
    """A stable subject handle for the `index`-th earner (higher earner first) -- keys the subject to
    its Social Security account and its subject removal."""
    return f'claimant-{index}'


def _nominal_by_year( result : ForecastResult, horizon : _Horizon ) -> list[ Decimal ]:
    """The run's per-year household Social Security nominal, indexed from the horizon start: the year-over-
    year change in the cumulative booked to the household's Social Security revenue accounts."""
    cumulative = _cumulative_social_security( result )
    nominals   = list()
    previous   = cumulative( horizon.start_year - 1 )
    for year in range( horizon.start_year, horizon.end_year + 1 ):
        through  = cumulative( year )
        nominals.append( through - previous )
        previous = through
        continue
    return nominals


def _year_benefits(
        nominals : list[ Decimal ], assumptions : Assumptions,
        horizon : _Horizon ) -> tuple[ YearBenefit, ... ]:
    """Each year's household Social Security discounted two ways: the `nominal` (deterministic, or the
    survival-weighted expected value), its `present_value` (discounted to start-year dollars at inflation,
    today's dollars), and its `effective_value` (discounted instead at the assumptions' discount rate -- the
    expected asset return when given, else inflation -- so it carries the opportunity cost of deferring)."""
    inflation_rate = assumptions.inflation.fraction
    effective_rate = assumptions.discount_rate.fraction
    benefits       = list()
    for periods, nominal in enumerate( nominals ):          # periods = years discounted from the start
        benefits.append( YearBenefit(
            year            = horizon.start_year + periods,
            nominal         = nominal,
            present_value   = nominal / ( _ONE + inflation_rate ) ** periods,
            effective_value = nominal / ( _ONE + effective_rate ) ** periods ) )
        continue
    return tuple( benefits )


def _cumulative_social_security( result : ForecastResult ):
    """A reader of the run's cumulative Social Security through a year-end -- summed across the
    household's Social Security revenue accounts (both members', including any retitled to the
    survivor on a death). A closure so a strategy's year loop reuses one books/ledger load."""
    reader   = Bookkeeper( result.books )
    accounts = [ account for account in result.books.accounts
                 if account.income_tax_class == IncomeTaxClass.SOCIAL_SECURITY ]

    def through( year : int ) -> Decimal:
        return sum( ( reader.ledger.natural_balance( account, through = date( year, 12, 31 ) )
                      for account in accounts ), Decimal( '0' ) )
    return through
