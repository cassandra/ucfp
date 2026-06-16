from typing import Tuple


def jaccard_coefficient( interval_1 : Tuple[ int, int ], interval_2 : Tuple[ int, int ] ):

    intersection = max(0, min( interval_1[1], interval_2[1]) - max(interval_1[0], interval_2[0] ))
    union = max( interval_1[1], interval_2[1]) - min(interval_1[0], interval_2[0] )
    if abs(union) < 0.0000000001:
        return 1.0
    else:
        return intersection / float( union )
