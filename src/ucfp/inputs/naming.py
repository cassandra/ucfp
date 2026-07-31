"""Shared naming helpers so a minted set's default name is unique from the start.

Component and scenario names are unique per organization (the rename UI enforces it too); these keep the
*auto-generated* defaults -- a new set's "Plans N", a clone's "<label> copy" -- from colliding, e.g. after
a middle set was deleted, or when the same set is cloned twice. Comparison is case-insensitive, matching
the rename check.
"""
from typing import Iterable


def numbered_label( prefix: str, taken: Iterable[ str ] ) -> str:
    """The first `prefix N` (N counting from 1) not among `taken` -- a distinguishable default new-set
    name that skips numbers already used."""
    used   = _lowered( taken )
    number = 1
    while f'{prefix} {number}'.lower() in used:
        number += 1
    return f'{prefix} {number}'


def unique_label( base: str, taken: Iterable[ str ] ) -> str:
    """`base` if free among `taken`, else `base 2`, `base 3`, ... -- for a derived name (a clone's copy)
    that must not collide with an existing one."""
    used = _lowered( taken )
    if base.lower() not in used:
        return base
    number = 2
    while f'{base} {number}'.lower() in used:
        number += 1
    return f'{base} {number}'


def _lowered( taken: Iterable[ str ] ) -> set:
    return { label.lower() for label in taken }
