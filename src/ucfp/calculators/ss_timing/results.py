"""View-model for the Social Security timing results page: the heatmap grid and the ranked list, built
from a `Comparison` so the view and template stay thin. The year-by-year detail is `compute.YearDetail`
(built by `compute.strategy_year_details`); this module shapes the two comparison-wide surfaces.

The heatmap is claiming-age by claiming-age (the higher earner's age down the rows, the lower earner's
across for a couple; a single row for one person), each cell shaded by its lifetime present value on a
sequential ramp. `combo` is a claim-age key ("67-67") the results page uses to drill into a cell.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .compute import CLAIM_AGES, Comparison

_HEAT_BUCKETS = 7     # sequential-ramp intensity levels (matched by the .hm-b0..6 classes in the stylesheet)
_RANK_LIMIT   = 10    # rows in the "Top strategies" list


@dataclass( frozen = True )
class HeatCell:
    """One heatmap cell: a claiming combination, its lifetime totals (nominal `raw_total` and
    `present_value`), and its ramp `bucket` (0 lowest .. `_HEAT_BUCKETS`-1 highest, shaded by present
    value). `combo` keys the drill-in; `is_best` marks the optimum, `is_selected` the shown cell."""

    combo         : str
    higher_age    : int
    lower_age     : Optional[ int ]
    raw_total     : Decimal
    present_value : Decimal
    bucket        : int
    is_best       : bool
    is_selected   : bool


@dataclass( frozen = True )
class RankRow:
    """One row of the ranked list: its `rank` (1 = best), the claiming `ages` (higher first), and both
    lifetime totals (`raw_total` and `present_value`). `combo` keys the drill-in; `is_best` /
    `is_selected` mirror the heatmap."""

    rank          : int
    combo         : str
    ages          : tuple[ int, ... ]
    raw_total     : Decimal
    present_value : Decimal
    is_best       : bool
    is_selected   : bool


def combo_of( claim_ages : tuple[ int, ... ] ) -> str:
    """A claim-age combination as a URL-safe key -- '67' for one person, '70-64' for a couple."""
    return '-'.join( str( age ) for age in claim_ages )


def heatmap( comparison : Comparison, selected_combo : str ) -> list[ list[ HeatCell ] ]:
    """The cells as rows: one row per higher-earner claim age (each column a lower-earner claim age) for a
    couple, a single row for one person. Shading buckets span the sweep's present-value range."""
    by_combo = { combo_of( strategy.claim_ages ): strategy for strategy in comparison.strategies }
    bucket   = _bucketer( comparison )
    best     = combo_of( comparison.best.claim_ages )
    if len( comparison.claimants ) == 1:
        return [ [ _cell( ( age, ), by_combo, bucket, best, selected_combo ) for age in CLAIM_AGES ] ]
    return [ [ _cell( ( higher, lower ), by_combo, bucket, best, selected_combo )
               for lower in CLAIM_AGES ]
             for higher in CLAIM_AGES ]


def ranked( comparison : Comparison, selected_combo : str ) -> list[ RankRow ]:
    """The top strategies by present value (best first), for the ranked list beside the heatmap."""
    best = combo_of( comparison.best.claim_ages )
    rows = list()
    for rank, strategy in enumerate( comparison.ranked[ : _RANK_LIMIT ], start = 1 ):
        combo = combo_of( strategy.claim_ages )
        rows.append( RankRow(
            rank = rank, combo = combo, ages = strategy.claim_ages,
            raw_total = strategy.raw_total, present_value = strategy.present_value,
            is_best = combo == best, is_selected = combo == selected_combo ) )
    return rows


def _cell( claim_ages, by_combo, bucket, best_combo, selected_combo ) -> HeatCell:
    combo    = combo_of( claim_ages )
    strategy = by_combo[ combo ]
    return HeatCell(
        combo         = combo,
        higher_age    = claim_ages[ 0 ],
        lower_age     = claim_ages[ 1 ] if len( claim_ages ) == 2 else None,
        raw_total     = strategy.raw_total,
        present_value = strategy.present_value,
        bucket        = bucket( strategy.present_value ),
        is_best       = combo == best_combo,
        is_selected   = combo == selected_combo )


def _bucketer( comparison : Comparison ):
    """A present-value -> ramp-bucket function over the sweep's range (all one bucket when flat)."""
    values = [ strategy.present_value for strategy in comparison.strategies ]
    low    = min( values )
    span   = max( values ) - low

    def bucket( present_value : Decimal ) -> int:
        if span == 0:
            return _HEAT_BUCKETS - 1
        share = ( present_value - low ) / span
        return min( int( share * _HEAT_BUCKETS ), _HEAT_BUCKETS - 1 )
    return bucket
