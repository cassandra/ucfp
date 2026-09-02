"""Social Security claiming-strategy comparison: sweep the age-62..70 claiming grid and rank the
strategies by lifetime benefit, via the forecast engine.

The couple-aware benefit -- each person's own, the lower earner's spousal top-up once both collect,
and the survivor step-up after a death -- lives in the engine
(`jurisdiction.social_security_household`, invoked per period). This module is the specialized,
Social-Security-only materialization above it: from a household's claiming facts it builds a
stripped `ForecastParameters` (subjects + Social Security entitlements + expected-lifetime removals +
the economic outlook), runs one forecast per claiming combination, and reduces each run's booked
Social Security to a lifetime total -- the nominal ("raw") sum and its present value.

Every strategy runs over one shared horizon -- from the earliest age-62 claim in the household to the
last expected death -- so early claiming's extra years and late claiming's larger checks are weighed
on equal footing. Present value discounts each year's benefit at the assumptions' `discount_rate` -- the
visitor's expected asset return when one is given, else general inflation (the app's "today's
dollars" convention, `overview._in_start_year_dollars`). Discounting at the expected return prices in the
opportunity cost of deferring benefits (money drawn from savings to bridge the wait forfeits its
compounding); discounting at inflation is the zero-real-opportunity-cost view. The discount base is the
start (age-62) year, shared by every strategy.

For the results drill-in, `strategy_year_details` apportions each year's engine household total into the
members' own / spousal / survivor parts. Because the COLA and reduction scale the whole benefit uniformly,
the parts' ratios are overlay-free: the split comes from the jurisdiction breakdown while the totals stay
the engine's -- so no economic overlay is reproduced here, and the per-person figures never read the books
(sidestepping the engine's account-retitling on a death).
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
from ucfp.jurisdiction.social_security_household import HouseholdMember, household_benefit_breakdown


EARLIEST_CLAIM_AGE = 62
LATEST_CLAIM_AGE   = 70
CLAIM_AGES         = tuple( range( EARLIEST_CLAIM_AGE, LATEST_CLAIM_AGE + 1 ) )

# The calculator is US-only (the FRA/PIA rules behind the benefit are the US ones); the facade is
# stateless, so a single instance serves the per-person breakdown split.
_GOVERNMENT_PENSION = GovernmentPension( JurisdictionType.US_FEDERAL )

# The Social Security COLA (tied to CPI-W) has historically trailed general inflation; rather than ask for
# both, the calculator takes one inflation figure and derives the COLA as inflation less this lag. A single
# familiar input, at the cost of a fixed assumed gap (see the results page's methodology note).
COLA_INFLATION_LAG = Rate( Decimal( '0.003' ) )

# The upper bound of the claiming crossover search: a real return above ~20% is not a realistic hurdle, so
# beyond it we simply report that delaying wins at any sane return rather than a precise threshold.
_CROSSOVER_MAX_REAL = Decimal( '0.20' )


@dataclass( frozen = True )
class Claimant:
    """One person's Social Security facts for the comparison: their `name`, `birth_year`, monthly
    PIA (`pia_monthly` -- the benefit at full retirement age, in start-year dollars) and
    `expected_lifetime` -- the age through which they are assumed to live, after which their benefit
    ends. Birthdays are modeled on January 1, so a claiming age lands on an exact date."""

    name              : str
    birth_year        : int
    pia_monthly       : Decimal
    expected_lifetime : int

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
    reduction_year   : int            = 2032
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
                        reduction_year : int = 2032,
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
    """One year of a strategy: the household's total Social Security that year, `nominal` (as paid --
    COLA-grown and shortfall-reduced) and `present_value` (discounted to start-year dollars)."""

    year          : int
    nominal       : Decimal
    present_value : Decimal


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
    higher first), each member's age, the `household` total and its `present_value` (both the engine's),
    and `is_transition` -- the first-death year where the survivor benefit begins."""

    year          : int
    ages          : tuple[ int, ... ]
    members       : tuple[ MemberYear, ... ]
    household     : Decimal
    present_value : Decimal
    is_transition : bool

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
    person). `raw_total` is the nominal lifetime sum; `present_value` discounts it to start-year
    dollars -- the figure strategies are ranked by. `year_benefits` is the year-by-year detail."""

    claim_ages    : tuple[ int, ... ]
    raw_total     : Decimal
    present_value : Decimal
    year_benefits : tuple[ YearBenefit, ... ]


@dataclass( frozen = True )
class Comparison:
    """The full sweep: the `claimants` (higher earner first) and every `Strategy` over the 62..70
    grid (9 for one person, 81 for a couple). `best` and `ranked` are derived so the heatmap and the
    ranked list read one settled result."""

    claimants  : tuple[ Claimant, ... ]
    strategies : tuple[ Strategy, ... ]

    @property
    def best( self ) -> Strategy:
        """The strategy with the greatest present value -- the one the results page marks."""
        return max( self.strategies, key = lambda strategy: strategy.present_value )

    @property
    def ranked( self ) -> tuple[ Strategy, ... ]:
        """Strategies from best to worst by present value -- the ranked-list order."""
        return tuple( sorted(
            self.strategies, key = lambda strategy: strategy.present_value, reverse = True ) )


@dataclass( frozen = True )
class Crossover:
    """Where claiming everyone as early as possible ties, in present value, with delaying everyone to 70 --
    the real return above which claiming early comes out ahead. `state` names the three cases the results
    page phrases: `threshold` (the crossover falls in a realistic range, in `real_return`), `early_wins`
    (claiming early already wins even at a 0% real return -- typically a short life expectancy), and
    `delay_wins` (delaying still wins even at the search cap, so no realistic return favors early)."""

    state       : str
    real_return : Optional[ Rate ] = None


def compare_claiming_strategies(
        claimants : list[ Claimant ], assumptions : Assumptions ) -> Comparison:
    """Sweep the 62..70 claiming grid for `claimants` (one person or a couple) and rank the
    strategies by lifetime present value. Each combination is a full engine run over the shared
    horizon; the couple's spousal and survivor benefits, the COLA, and the funding-shortfall
    reduction all come from the engine. Claimants are ordered by PIA (higher earner first), the
    orientation the results grid reads."""
    if not 1 <= len( claimants ) <= 2:
        raise ValueError(
            f'A Social Security comparison covers one person or a couple; got {len( claimants )}.' )
    earners      = tuple( sorted(
        claimants, key = lambda claimant: claimant.pia_monthly, reverse = True ) )
    horizon      = _Horizon.for_household( earners )
    combinations = product( CLAIM_AGES, repeat = len( earners ) )
    strategies   = tuple(
        _run_strategy( earners, claim_ages, assumptions, horizon )
        for claim_ages in combinations )
    return Comparison( claimants = earners, strategies = strategies )


def compute_strategy(
        claimants : list[ Claimant ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions ) -> Strategy:
    """One strategy for a chosen claiming combination (the higher earner's age first) -- the results page's
    drill-in recompute, a single engine run rather than the whole sweep. Claimants are ordered by PIA, so
    `claim_ages` aligns to the heatmap's axes."""
    earners = tuple( sorted( claimants, key = lambda claimant: claimant.pia_monthly, reverse = True ) )
    return _run_strategy( earners, claim_ages, assumptions, _Horizon.for_household( earners ) )


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
            year          = benefit.year,
            ages          = tuple( benefit.year - earner.birth_year for earner in earners ),
            members       = member_years,
            household     = benefit.nominal,
            present_value = benefit.present_value,
            is_transition = has_survivor and not seen_survivor ) )
        seen_survivor = seen_survivor or has_survivor
        continue
    return tuple( details )


def claiming_crossover( comparison : Comparison, inflation : Rate ) -> Optional[ Crossover ]:
    """The real return at which claiming everyone as early as possible ties, in present value, with
    delaying everyone to 70 -- the crossover that frames the whole early-vs-late question (below it delaying
    wins, above it claiming early does). Pure arithmetic over the two strategies' fixed nominal streams (the
    discount never changed the benefits), so no re-run. None when the household has no all-62 / all-70
    strategy to compare; otherwise a `Crossover` naming which of the three cases holds."""
    earliest = _strategy_with_uniform_age( comparison, EARLIEST_CLAIM_AGE )
    latest   = _strategy_with_uniform_age( comparison, LATEST_CLAIM_AGE )
    if earliest is None or latest is None:
        return None
    start = earliest.year_benefits[ 0 ].year                             # the shared horizon (age-62) start

    def surplus( real : Decimal ) -> Decimal:
        """Delaying's present-value advantage at real return `real` (nominal = inflation + real)."""
        nominal = inflation.fraction + real
        return ( _present_value_at( latest.year_benefits, nominal, start )
                 - _present_value_at( earliest.year_benefits, nominal, start ) )

    if surplus( Decimal( '0' ) ) <= 0:                                   # early wins even at a 0% real return
        return Crossover( state = 'early_wins' )
    if surplus( _CROSSOVER_MAX_REAL ) >= 0:                              # delay wins even at the search cap
        return Crossover( state = 'delay_wins' )
    low, high = Decimal( '0' ), _CROSSOVER_MAX_REAL                      # bisect the single crossing between
    for _ in range( 60 ):
        mid = ( low + high ) / 2
        if surplus( mid ) > 0:
            low = mid
        else:
            high = mid
        continue
    return Crossover( state = 'threshold', real_return = Rate( ( low + high ) / 2 ) )


def _strategy_with_uniform_age( comparison : Comparison, age : int ) -> Optional[ Strategy ]:
    """The strategy where every claimant claims at `age` (the all-62 or all-70 combination), or None."""
    target = tuple( age for _ in comparison.claimants )
    return next( ( strategy for strategy in comparison.strategies if strategy.claim_ages == target ), None )


def _present_value_at(
        year_benefits : tuple[ YearBenefit, ... ], rate : Decimal, start_year : int ) -> Decimal:
    """A fixed nominal benefit stream's present value discounted at nominal `rate` to `start_year`."""
    return sum( ( benefit.nominal / ( Decimal( '1' ) + rate ) ** ( benefit.year - start_year )
                  for benefit in year_benefits ), Decimal( '0' ) )


def _household_members(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ] ) -> list[ HouseholdMember ]:
    """The jurisdiction calculator's members for this combination -- each earner claiming at their swept
    age and leaving at their expected lifetime -- handles index-keyed to the earners (higher first), the
    same keys the forecast used, so the breakdown reads back in that order."""
    return [
        HouseholdMember(
            subject_handle = _handle( index ),
            birthdate      = earner.birthdate,
            pia_monthly    = earner.pia_monthly,
            claiming_date  = date( earner.birth_year + age, 1, 1 ),
            death_date     = date( earner.birth_year + earner.expected_lifetime, 1, 1 ) )
        for index, ( earner, age ) in enumerate( zip( earners, claim_ages ) ) ]


def _apportion( part, household_nominal : Decimal, today_total : Decimal ) -> MemberYear:
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
        start = min( claimant.birth_year + EARLIEST_CLAIM_AGE for claimant in claimants )
        end   = max( claimant.birth_year + claimant.expected_lifetime for claimant in claimants )
        return cls( start_year = start, end_year = end )


def _run_strategy(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, horizon : _Horizon ) -> Strategy:
    """One claiming combination: build its Social-Security-only forecast, run it, and reduce the
    booked benefit to per-year and lifetime totals (nominal and present value)."""
    parameters    = _forecast_parameters( earners, claim_ages, assumptions, horizon )
    result        = Forecast( parameters ).run()
    year_benefits = _year_benefits( result, assumptions, horizon )
    raw_total     = sum( ( benefit.nominal for benefit in year_benefits ), Decimal( '0' ) )
    present_value = sum( ( benefit.present_value for benefit in year_benefits ), Decimal( '0' ) )
    return Strategy(
        claim_ages = claim_ages, raw_total = raw_total,
        present_value = present_value, year_benefits = year_benefits )


def _forecast_parameters(
        earners : tuple[ Claimant, ... ], claim_ages : tuple[ int, ... ],
        assumptions : Assumptions, horizon : _Horizon ) -> ForecastParameters:
    """The stripped, Social-Security-only forecast for one claiming combination: a subject and SS
    entitlement per claimant (claiming at their swept age), an expected-lifetime removal each, a
    single cash hub for the benefits to land in, and the economic outlook -- no other income, assets,
    or expenses, so only the Social Security lines carry value."""
    subjects     = [ Subject( claimant.name, claimant.birthdate, handle = _handle( index ) )
                     for index, claimant in enumerate( earners ) ]
    entitlements = [
        SocialSecurityEntitlement(
            subject, claimant.pia_monthly, date( claimant.birth_year + age, 1, 1 ) )
        for subject, claimant, age in zip( subjects, earners, claim_ages ) ]
    removals     = [
        SubjectRemoval(
            date( claimant.birth_year + claimant.expected_lifetime, 1, 1 ), subject.handle )
        for subject, claimant in zip( subjects, earners ) ]
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
        economic_outlook = EconomicOutlook.constant( EconomicParameters(
            inflation                        = assumptions.inflation,
            social_security_cola             = assumptions.cola,
            social_security_benefits_payable = assumptions.benefits_payable,
            social_security_reduction_year   = assumptions.reduction_year ) ) )


def _handle( index : int ) -> str:
    """A stable subject handle for the `index`-th earner (higher earner first) -- keys the subject to
    its Social Security account and its expected-lifetime removal."""
    return f'claimant-{index}'


def _year_benefits(
        result : ForecastResult, assumptions : Assumptions,
        horizon : _Horizon ) -> tuple[ YearBenefit, ... ]:
    """Each year's household Social Security from the run's books, nominal and present-valued. The
    nominal figure is the total booked to the Social Security revenue accounts that year; present
    value discounts it to start-year dollars at the assumptions' discount rate (the expected asset
    return when given, else inflation)."""
    cumulative    = _cumulative_social_security( result )
    discount_rate = assumptions.discount_rate.fraction
    benefits      = list()
    previous      = cumulative( horizon.start_year - 1 )
    for year in range( horizon.start_year, horizon.end_year + 1 ):
        through  = cumulative( year )
        nominal  = through - previous
        previous = through
        discount = ( Decimal( '1' ) + discount_rate ) ** ( year - horizon.start_year )
        benefits.append( YearBenefit(
            year = year, nominal = nominal, present_value = nominal / discount ) )
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
