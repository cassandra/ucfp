import math
from typing import Tuple


def nice_ticks( low : float, high : float, count : int = 4 ) -> list[ float ]:
    """Round axis tick values spanning [low, high], as `count`-ish evenly spaced steps.

    Returns values on a "nice" step (1/2/5 x 10^n) covering the range -- the tick
    range may extend slightly beyond [low, high] so both ends land on round
    numbers. Purely numeric (no formatting); callers label the values as they see
    fit. Degenerate ranges (empty or zero-width) return a single endpoint.
    """
    if ( count < 1 ) or ( high <= low ):
        return [ low ]
    step  = _nice_step( ( high - low ) / count )
    start = math.floor( low  / step ) * step
    end   = math.ceil(  high / step ) * step
    ticks = []
    value = start
    while value <= end + ( step * 1e-9 ):
        ticks.append( round( value, 10 ) )
        value += step
    return ticks


def _nice_step( raw_step : float ) -> float:
    """The smallest 1/2/5 x 10^n step >= `raw_step` (the classic nice-number step)."""
    exponent = math.floor( math.log10( raw_step ) )
    magnitude = 10 ** exponent
    fraction = raw_step / magnitude
    if fraction <= 1:
        nice_fraction = 1
    elif fraction <= 2:
        nice_fraction = 2
    elif fraction <= 2.5:
        nice_fraction = 2.5
    elif fraction <= 5:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * magnitude


def jaccard_coefficient( interval_1 : Tuple[ int, int ], interval_2 : Tuple[ int, int ] ):

    intersection = max(0, min( interval_1[1], interval_2[1]) - max(interval_1[0], interval_2[0] ))
    union = max( interval_1[1], interval_2[1]) - min(interval_1[0], interval_2[0] )
    if abs(union) < 0.0000000001:
        return 1.0
    else:
        return intersection / float( union )
