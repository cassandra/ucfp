"""Process-local cache of a claiming-strategy sweep, keyed by its immutable inputs.

A couple's ACTUARIAL sweep is 243 engine runs (81 combinations x 3 survival states) -- a few seconds of
CPU. The sweep is a pure function of its inputs (the household's claimants, the economic assumptions, and
the life-expectancy basis), so a results page re-render or a refresh with unchanged inputs re-runs the
same work. This memoizes the sweep so those repeats become a lookup; only the first view of a given
household pays the compute.

Bounded to a handful of recent sweeps (LRU). A `Comparison` is small next to a reloaded run's books, so a
modest bound keeps a session's recent variations warm with a firm memory ceiling regardless of traffic.

Process-local by design (mirrors `planning.run_books_cache`): correctness never depends on process
affinity -- a miss simply recomputes -- so under multiple workers this degrades to partial hit-rates.
Keyed by the *value* signature of the inputs (all immutable, hashable dataclasses/enums), so the sweep is
a deterministic function of the key alone: a hit for one visitor is identical to what another with the
same figures would compute, leaking nothing beyond what those identical inputs already determine.

The returned `Comparison` is SHARED and read-only -- it is a frozen dataclass of frozen strategies, so
there is nothing to mutate, but callers must not attempt to.
"""
from collections import OrderedDict
from threading import Lock

from ucfp.calculators.ss_timing.compute import (
    Assumptions, Claimant, Comparison, LifeExpectancyBasis, compare_claiming_strategies, earners_of )


# Recent sweeps kept warm. A Comparison is far lighter than a run's books graph, so this bounds the cache
# to a few megabytes -- comfortable on a small host, and a firm ceiling however many households are swept.
_MAX_CACHED_SWEEPS = 32

_comparison_by_key : "OrderedDict" = OrderedDict()   # (earners, assumptions, basis) -> Comparison (LRU)
_lock = Lock()


def cached_comparison(
        claimants : list[ Claimant ], assumptions : Assumptions,
        basis : LifeExpectancyBasis = LifeExpectancyBasis.SPECIFIC ) -> Comparison:
    """The claiming-strategy sweep for `claimants` under `assumptions` and `basis`, served from the
    process-local cache when warm (see `compute.compare_claiming_strategies`).

    On a miss the sweep runs OUTSIDE the lock, so a slow sweep never blocks other requests and two
    simultaneous misses simply both compute (rare, and harmless -- they build equal results). The key is
    the PIA-ordered earners (so the two input orders of a couple share one entry) with the assumptions and
    basis."""
    key = ( earners_of( claimants ), assumptions, basis )
    with _lock:
        cached = _comparison_by_key.get( key )
        if cached is not None:
            _comparison_by_key.move_to_end( key )
            return cached
    comparison = compare_claiming_strategies( claimants, assumptions, basis )
    with _lock:
        _comparison_by_key[ key ] = comparison
        _comparison_by_key.move_to_end( key )
        while len( _comparison_by_key ) > _MAX_CACHED_SWEEPS:
            _comparison_by_key.popitem( last = False )
    return comparison


def clear_comparison_cache() -> None:
    """Drop every cached sweep. Ordinary operation needs no invalidation -- a sweep is a pure function of
    its inputs -- so this is for test hygiene and any future explicit-eviction need."""
    with _lock:
        _comparison_by_key.clear()
