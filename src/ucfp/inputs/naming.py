"""Shared naming helpers so a minted set's default name is unique from the start.

Component and scenario names are unique per organization (the rename UI enforces it too); these keep the
*auto-generated* defaults -- a new set's "Plans N", a clone's "<label> copy" -- from colliding, e.g. after
a middle set was deleted, or when the same set is cloned twice. Comparison is case-insensitive, matching
the rename check.
"""


def numbered_label( prefix: str, taken ) -> str:
    """The first `prefix N` (N counting from 1) not among `taken` -- a distinguishable default new-set
    name that skips numbers already used."""
    lowered = { label.lower() for label in taken }
    number  = 1
    while f'{prefix} {number}'.lower() in lowered:
        number += 1
    return f'{prefix} {number}'


def unique_label( base: str, taken ) -> str:
    """`base` if free among `taken`, else `base 2`, `base 3`, ... -- for a derived name (a clone's copy)
    that must not collide with an existing one."""
    lowered = { label.lower() for label in taken }
    if base.lower() not in lowered:
        return base
    number = 2
    while f'{base} {number}'.lower() in lowered:
        number += 1
    return f'{base} {number}'
