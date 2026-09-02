"""View-model for the Social Security timing results page: the heatmap grid and the ranked list, built
from a `Comparison` so the view and template stay thin. The year-by-year detail is `compute.YearDetail`
(built by `compute.strategy_year_details`); this module shapes the two comparison-wide surfaces.

The heatmap is claiming-age by claiming-age (the higher earner's age down the rows, the lower earner's
across for a couple; a single row for one person), each cell shaded by its lifetime effective value (the
opportunity-cost-adjusted figure strategies are ranked by) on a sequential ramp. `combo` is a claim-age
key ("67-67") the results page uses to drill into a cell.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .compute import CLAIM_AGES, Claimant, Comparison, Sex

_HEAT_BUCKETS = 7     # sequential-ramp intensity levels (matched by the .hm-b0..6 classes in the stylesheet)
_RANK_LIMIT   = 10    # rows in the "Top strategies" list


@dataclass( frozen = True )
class HeatCell:
    """One heatmap cell: a claiming combination, its lifetime figures (`raw_total`, `present_value`, and
    `effective_value` -- the opportunity-cost-adjusted figure it is shaded and ranked by), and its ramp
    `bucket` (0 lowest .. `_HEAT_BUCKETS`-1 highest). `combo` keys the drill-in; `is_best` marks the
    optimum, `is_selected` the shown cell."""

    combo           : str
    higher_age      : int
    lower_age       : Optional[ int ]
    raw_total       : Decimal
    present_value   : Decimal
    effective_value : Decimal
    bucket          : int
    is_best         : bool
    is_selected     : bool


@dataclass( frozen = True )
class RankRow:
    """One row of the ranked list: its `rank` (1 = best), the claiming `ages` (higher first), and its three
    lifetime figures -- nominal `raw_total`, `present_value` (today's dollars), and `effective_value` (the
    opportunity-cost-adjusted figure it is ranked by). `combo` keys the drill-in; `is_best` / `is_selected`
    mirror the heatmap."""

    rank            : int
    combo           : str
    ages            : tuple[ int, ... ]
    raw_total       : Decimal
    present_value   : Decimal
    effective_value : Decimal
    is_best         : bool
    is_selected     : bool


@dataclass( frozen = True )
class PersonRecap:
    """One person in the household recap panel: their `name`, `role` label ('higher earner' / 'lower
    earner', or None for a single household), monthly `pia`, the assumed `lifetime_age`, and -- under the
    actuarial basis -- the `basis_words` describing where that age came from ('male, average'); empty in
    the specific basis, where the age was entered rather than estimated."""

    name         : str
    role         : Optional[ str ]
    pia          : Decimal
    lifetime_age : Optional[ int ]
    basis_words  : str


def combo_of( claim_ages : tuple[ int, ... ] ) -> str:
    """A claim-age combination as a URL-safe key -- '67' for one person, '70-64' for a couple."""
    return '-'.join( str( age ) for age in claim_ages )


def person_recaps( earners : tuple[ Claimant, ... ], estimated : bool ) -> list[ PersonRecap ]:
    """The household recap rows for `earners` (higher first). `estimated` marks the actuarial basis, where
    the lifetime age is the derived life expectancy and `basis_words` names the survival curve used;
    otherwise the age was entered and the words are blank. Each earner must carry `expected_lifetime` (the
    entered age, or the representative age filled by `compute.representative_claimants`)."""
    is_couple = len( earners ) == 2
    recaps    = list()
    for index, earner in enumerate( earners ):
        role = None
        if is_couple:
            role = 'higher earner' if index == 0 else 'lower earner'
        recaps.append( PersonRecap(
            name         = earner.name,
            role         = role,
            pia          = earner.pia_monthly,
            lifetime_age = earner.expected_lifetime,
            basis_words  = _basis_words( earner ) if estimated else '' ) )
        continue
    return recaps


def _basis_words( claimant : Claimant ) -> str:
    """The survival curve behind a claimant's estimated life expectancy, as a short phrase -- the mortality
    table and the longevity setback, e.g. 'male, average' or 'blended, longer-lived'."""
    table     = { Sex.FEMALE: 'female', Sex.MALE: 'male' }.get( claimant.sex, 'blended' )
    setback   = claimant.setback
    longevity = 'shorter-lived' if setback > 0 else 'longer-lived' if setback < 0 else 'average'
    return f'{table}, {longevity}'


def heatmap( comparison : Comparison, selected_combo : str ) -> list[ list[ HeatCell ] ]:
    """The cells as rows: one row per higher-earner claim age (each column a lower-earner claim age) for a
    couple, a single row for one person. Shading buckets span the sweep's effective-value range."""
    by_combo = { combo_of( strategy.claim_ages ): strategy for strategy in comparison.strategies }
    bucket   = _bucketer( comparison )
    best     = combo_of( comparison.best.claim_ages )
    if len( comparison.claimants ) == 1:
        return [ [ _cell( ( age, ), by_combo, bucket, best, selected_combo ) for age in CLAIM_AGES ] ]
    return [ [ _cell( ( higher, lower ), by_combo, bucket, best, selected_combo )
               for lower in CLAIM_AGES ]
             for higher in CLAIM_AGES ]


def ranked( comparison : Comparison, selected_combo : str ) -> list[ RankRow ]:
    """The top strategies by effective value (best first), for the ranked list beside the heatmap."""
    best = combo_of( comparison.best.claim_ages )
    rows = list()
    for rank, strategy in enumerate( comparison.ranked[ : _RANK_LIMIT ], start = 1 ):
        combo = combo_of( strategy.claim_ages )
        rows.append( RankRow(
            rank = rank, combo = combo, ages = strategy.claim_ages,
            raw_total = strategy.raw_total, present_value = strategy.present_value,
            effective_value = strategy.effective_value,
            is_best = combo == best, is_selected = combo == selected_combo ) )
        continue
    return rows


def _cell( claim_ages, by_combo, bucket, best_combo, selected_combo ) -> HeatCell:
    combo    = combo_of( claim_ages )
    strategy = by_combo[ combo ]
    return HeatCell(
        combo           = combo,
        higher_age      = claim_ages[ 0 ],
        lower_age       = claim_ages[ 1 ] if len( claim_ages ) == 2 else None,
        raw_total       = strategy.raw_total,
        present_value   = strategy.present_value,
        effective_value = strategy.effective_value,
        bucket          = bucket( strategy.effective_value ),
        is_best         = combo == best_combo,
        is_selected     = combo == selected_combo )


def _bucketer( comparison : Comparison ):
    """An effective-value -> ramp-bucket function over the sweep's range (all one bucket when flat)."""
    values = [ strategy.effective_value for strategy in comparison.strategies ]
    low    = min( values )
    span   = max( values ) - low

    def bucket( effective_value : Decimal ) -> int:
        if span == 0:
            return _HEAT_BUCKETS - 1
        share = ( effective_value - low ) / span
        return min( int( share * _HEAT_BUCKETS ), _HEAT_BUCKETS - 1 )
    return bucket
