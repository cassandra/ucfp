"""Value-level diff of two Profiles -- what household *facts* changed between them.

The run twin of `explore_diff.value_changes` (which diffs the Scenario dials): this compares two Profile
snapshots and yields short human descriptions of the facts that differ. It surfaces on the Explore
workspace when an exploration's runs were computed against an earlier Profile than the current one, so the
user can see exactly which facts moved before re-baselining. Matches records by their stable `handle`
(subjects/assets/debts/income/leases) or `subject_handle` (entitlements): a missing one reads as added or
removed, a present one as its changed fields.
"""
from decimal import Decimal

from ucfp.inputs.profile.schemas import Profile

_ZERO = Decimal( '0' )


def profile_changes( before: Profile, after: Profile ) -> list:
    """Short descriptions of the Profile facts that differ from `before` to `after` (empty when identical)."""
    return (
        _household_changes( before, after )
        + _asset_changes( before.assets, after.assets )
        + _debt_changes( before.debts, after.debts )
        + _income_changes( before.income_flows, after.income_flows )
        + _pension_changes( before.pensions, after.pensions )
        + _government_pension_changes( before.government_pension, after.government_pension )
        + _leased_vehicle_changes( before.leased_vehicles, after.leased_vehicles ) )


def _household_changes( before: Profile, after: Profile ) -> list:
    changes = list()
    if before.filing_status != after.filing_status:
        changes.append( f'Filing status {_label( before.filing_status )} → {_label( after.filing_status )}' )
    if before.home_tenure != after.home_tenure:
        changes.append( f'Housing {_label( before.home_tenure )} → {_label( after.home_tenure )}' )
    if before.jurisdiction_type != after.jurisdiction_type:
        changes.append( f'Jurisdiction {_label( before.jurisdiction_type )} → {_label( after.jurisdiction_type )}' )
    if before.us_state != after.us_state:
        changes.append( f'State {_label( before.us_state )} → {_label( after.us_state )}' )
    if before.state_income_tax_rate.fraction != after.state_income_tax_rate.fraction:
        changes.append(
            f'State income tax {_pct( before.state_income_tax_rate.fraction )}%'
            f' → {_pct( after.state_income_tax_rate.fraction )}%' )
    changes += _subject_changes( before.subjects, after.subjects )
    return changes


def _subject_changes( before, after ) -> list:
    earlier_by = _by( before )
    changes    = list()
    for later in after:
        earlier = earlier_by.get( later.handle )
        if earlier is None:
            changes.append( f'Added household member {later.name}' )
            continue
        if earlier.name != later.name:
            changes.append( f'{earlier.name} renamed to {later.name}' )
        if earlier.birthdate != later.birthdate:
            changes.append( f'{later.name} birthdate {earlier.birthdate} → {later.birthdate}' )
    return changes + _removed( before, after, lambda s: f'Removed household member {s.name}' )


def _asset_changes( before, after ) -> list:
    earlier_by = _by( before )
    changes    = list()
    for later in after:
        earlier = earlier_by.get( later.handle )
        if earlier is None:
            changes.append( f'Added {later.name} ({_money( later.opening_value )})' )
            continue
        if earlier.opening_value != later.opening_value:
            changes.append( f'{later.name} value {_money( earlier.opening_value )} → {_money( later.opening_value )}' )
        if ( earlier.cost_basis or _ZERO ) != ( later.cost_basis or _ZERO ):
            changes.append(
                f'{later.name} basis {_money( earlier.cost_basis or _ZERO )} → {_money( later.cost_basis or _ZERO )}' )
        if earlier.asset_class != later.asset_class:
            changes.append( f'{later.name} type {_label( earlier.asset_class )} → {_label( later.asset_class )}' )
    return changes + _removed( before, after, lambda a: f'Removed {a.name}' )


def _debt_changes( before, after ) -> list:
    earlier_by = _by( before )
    changes    = list()
    for later in after:
        earlier = earlier_by.get( later.handle )
        if earlier is None:
            changes.append( f'Added debt {later.name} ({_money( later.balance )})' )
            continue
        if earlier.balance != later.balance:
            changes.append( f'{later.name} balance {_money( earlier.balance )} → {_money( later.balance )}' )
    return changes + _removed( before, after, lambda d: f'Removed debt {d.name}' )


def _income_changes( before, after ) -> list:
    earlier_by = _by( before )
    changes    = list()
    for later in after:
        earlier = earlier_by.get( later.handle )
        if earlier is None:
            changes.append( f'Added income {later.name} ({_money( later.amount )})' )
            continue
        if earlier.amount != later.amount:
            changes.append( f'{later.name} income {_money( earlier.amount )} → {_money( later.amount )}' )
    return changes + _removed( before, after, lambda f: f'Removed income {f.name}' )


def _pension_changes( before, after ) -> list:
    earlier_by = _by( before, key = lambda p: p.subject_handle )
    changes    = list()
    for later in after:
        earlier = earlier_by.get( later.subject_handle )
        if earlier is None:
            changes.append( f'Added pension for {later.subject_handle}' )
            continue
        if earlier.base_annual_amount != later.base_annual_amount:
            changes.append(
                f'Pension ({later.subject_handle}) {_money( earlier.base_annual_amount )}'
                f' → {_money( later.base_annual_amount )}' )
        if earlier.normal_start_age != later.normal_start_age:
            changes.append(
                f'Pension age ({later.subject_handle}) {earlier.normal_start_age} → {later.normal_start_age}' )
    return changes + _removed(
        before, after, lambda p: f'Removed pension for {p.subject_handle}', key = lambda p: p.subject_handle )


def _government_pension_changes( before, after ) -> list:
    earlier_by = _by( before, key = lambda g: g.subject_handle )
    changes    = list()
    for later in after:
        earlier = earlier_by.get( later.subject_handle )
        if earlier is None:
            changes.append( f'Added state pension for {later.subject_handle}' )
            continue
        if earlier.monthly_at_normal_age != later.monthly_at_normal_age:
            changes.append(
                f'State pension ({later.subject_handle}) {_money( earlier.monthly_at_normal_age )}/mo'
                f' → {_money( later.monthly_at_normal_age )}/mo' )
    return changes + _removed(
        before, after, lambda g: f'Removed state pension for {g.subject_handle}',
        key = lambda g: g.subject_handle )


def _leased_vehicle_changes( before, after ) -> list:
    earlier_by = _by( before )
    changes    = [ f'Added leased vehicle {later.name}' for later in after if later.handle not in earlier_by ]
    return changes + _removed( before, after, lambda v: f'Removed leased vehicle {v.name}' )


def _by( items, key = lambda item: item.handle ) -> dict:
    return { key( item ): item for item in items }


def _removed( before, after, describe, key = lambda item: item.handle ) -> list:
    present = { key( item ) for item in after }
    return [ describe( item ) for item in before if key( item ) not in present ]


def _label( value ) -> str:
    """A labelled-enum's display label, or an em dash for an unset (None) fact."""
    if value is None:
        return '—'
    return getattr( value, 'label', str( value ) )


def _money( amount: Decimal ) -> str:
    return f'${amount:,.0f}'


def _pct( fraction: Decimal ) -> str:
    return f'{fraction * 100:g}'
