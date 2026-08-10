"""The vehicle handle scheme: one home for every handle a vehicle's accounts and its derived vehicles are
minted under, and the inverse -- recovering the root vehicle any of them belongs to.

A vehicle's identity is its `vehicle-N` handle (minted among all current vehicles, owned or leased). From
it we derive:

  - the holding account          `vehicle:{v}`               -- an owned car's depreciating asset
  - the loan liability account   `vehicle-loan:{v}`          -- the engine appends `:{cycle}` per
                                                                 replacement cycle of a recurring loan
  - the loan interest account    `vehicle-loan-interest:{v}` -- likewise `:{cycle}`
  - the secured-loan debt fact   `{v}-loan`                  -- the Profile `Debt(AUTO)` identity
  - a Replace successor          `{v}-replacement`           -- materialized as a fresh vehicle
  - a leased successor           `{v}-successor`             -- a Renew/Buy at lease end

`root_vehicle` is the inverse used wherever accounts must be grouped or resolved back to their vehicle
(the run table's per-vehicle rollups, a sale's loan payoff): it strips whichever account prefix, cycle
suffix, or derivation suffix a handle carries and returns the `vehicle-N` it belongs to, or None for a
handle outside the scheme.

Pure string identities -- no imports, so any layer may depend on it.
"""
from typing import Optional


VEHICLE_PREFIX = 'vehicle-'   # every vehicle handle is `vehicle-N`; the derived handles build on it

_HOLDING_PREFIX       = 'vehicle'
_LOAN_PREFIX          = 'vehicle-loan'
_LOAN_INTEREST_PREFIX = 'vehicle-loan-interest'

# The account prefixes (the segment before the first ':') that scope an account to its vehicle. A handle
# carries exactly one, matched by its head token -- so `vehicle-loan-interest` never reads as `vehicle-loan`.
_ACCOUNT_PREFIXES = frozenset( ( _HOLDING_PREFIX, _LOAN_PREFIX, _LOAN_INTEREST_PREFIX ) )

# The suffixes that derive one handle from a vehicle handle (a secured-loan debt, a replacement, a leased
# successor). A given handle carries at most one, so a single strip recovers the vehicle.
_DERIVATION_SUFFIXES = ( '-loan', '-replacement', '-successor' )


def vehicle_holding_handle( vehicle_handle : str ) -> str:
    """The account handle of an owned vehicle's holding -- scoped to the vehicle so each car is its own
    depreciating asset."""
    return f'{_HOLDING_PREFIX}:{vehicle_handle}'


def vehicle_loan_handle( vehicle_handle : str ) -> str:
    """The base liability handle for a financed vehicle's loan. The engine appends the replacement cycle
    (each replacement originates its own loan), so a recurring loan's first cycle is `vehicle-loan:<v>:0`;
    a current vehicle's loan is the cycle-less `vehicle-loan:<v>`."""
    return f'{_LOAN_PREFIX}:{vehicle_handle}'


def vehicle_loan_interest_handle( vehicle_handle : str ) -> str:
    """The interest expense account handle mirroring `vehicle_loan_handle` (the engine appends the cycle
    likewise)."""
    return f'{_LOAN_INTEREST_PREFIX}:{vehicle_handle}'


def loan_debt_handle( vehicle_handle : str ) -> str:
    """The stable handle of the `Debt(AUTO)` fact securing an owned vehicle -- derived from the vehicle's
    own handle (mirroring a mortgage's `{handle}-mortgage`), so the pair travels together and a sale, a
    delete, or a switch to leased can find it."""
    return f'{vehicle_handle}-loan'


def replacement_handle( vehicle_handle : str ) -> str:
    """The identity of the successor a Replace disposition buys -- derived from the current vehicle's
    handle, so it is stable and distinct from any net-new vehicle's `vehicle-N`."""
    return f'{vehicle_handle}-replacement'


def successor_handle( vehicle_handle : str ) -> str:
    """The identity of the successor a Renew or Buy disposition starts at lease end -- derived from the
    leased vehicle's handle, so it is stable and distinct from any other vehicle."""
    return f'{vehicle_handle}-successor'


def is_vehicle_loan_handle( handle : str ) -> bool:
    """True for a vehicle loan *liability* account handle (`vehicle-loan:<v>`, the engine's `:cycle`
    suffix included) -- distinguished from an interest handle by its exact head token, so
    `vehicle-loan-interest:` never reads as a loan."""
    return handle.partition( ':' )[ 0 ] == _LOAN_PREFIX


def is_vehicle_loan_interest_handle( handle : str ) -> bool:
    """True for a vehicle loan *interest* expense account handle (`vehicle-loan-interest:<v>`, `:cycle`
    included)."""
    return handle.partition( ':' )[ 0 ] == _LOAN_INTEREST_PREFIX


def root_vehicle( handle : str ) -> Optional[ str ]:
    """The `vehicle-N` a handle belongs to, or None for a handle outside the vehicle scheme. Resolves any
    account handle (`vehicle:`, `vehicle-loan:`, `vehicle-loan-interest:`, with or without a `:cycle`), a
    derived vehicle (`-replacement`/`-successor`), or a secured-loan debt (`-loan`) back to the vehicle it
    derives from -- so a current vehicle and its replacements, loans, and interest all resolve to one root."""
    vehicle = _vehicle_of( handle )
    if vehicle is None:
        return None
    return _strip_derivation( vehicle )


def _vehicle_of( handle : str ) -> Optional[ str ]:
    """The vehicle handle an account handle scopes to (before any derivation strip): the token after a
    known account prefix (dropping a trailing `:cycle`), or the handle itself when it is already a vehicle
    handle. None for anything else."""
    head, separator, rest = handle.partition( ':' )
    if head in _ACCOUNT_PREFIXES:
        return rest.split( ':', 1 )[ 0 ] or None            # `{prefix}:{vehicle}[:cycle]`
    if separator == '' and handle.startswith( VEHICLE_PREFIX ):
        return handle                                       # already a (possibly derived) vehicle handle
    return None


def _strip_derivation( vehicle_handle : str ) -> str:
    """A vehicle handle with any single derivation suffix removed -- so a replacement, successor, or
    secured-loan debt resolves to the vehicle it was derived from."""
    for suffix in _DERIVATION_SUFFIXES:
        if vehicle_handle.endswith( suffix ):
            return vehicle_handle[ : -len( suffix ) ]
    return vehicle_handle
