"""The BooksTable: a drill-down tabular view over a `BooksOfAccount`.

A general presentation model -- not tied to any one caller (a forecast run is the first, but
the layer takes only a `Ledger`/`Chart` and a sequence of period `DateSpan`s). It arranges the
books as rows (one per period) by columns, where a column is one of four `BooksColumnKind`s:
a type rollup, a class rollup, a single account, or a derived figure. Summary columns (type,
class) roll up their members and can be expanded into them; leaf columns (account, derived)
cannot.

The pieces:
  - `BooksColumnKey`  -- an opaque, kind-prefixed token identifying a column (and the unit a
                         persisted `BooksTableDefinition` stores). Accounts key by `account_uuid`.
  - `BooksColumn`     -- a column in the catalog: its key, display label, parent, and (for a
                         summary) its member keys.
  - `BooksTableColumnCatalog` -- every column a given books offers, and the default view.
  - `BooksTableDefinition`    -- an ordered set of visible column keys (the view to render).
  - `build_books_table`       -- resolves a definition against the books into rendered cells.

Cell values honor the stock/flow split: asset/liability/equity (and Net Worth) read as a
balance at period end (assets at market value); revenue/expense read as a flow over the period.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

from common.date_span import DateSpan
from common.labeled_enum import LabeledEnum

from .books import AccountDisplayGroup, AccountDisplayPlacement
from .chart import Chart
from .enums import (
    AccountClass,
    AccountType,
    AssetClass,
    ExpenseTaxClass,
    IncomeTaxClass,
)
from .ledger import Ledger


class BooksColumnKind( LabeledEnum ):
    """What a column draws its per-period figure from -- the four column variants. The lowercase
    member name is the column key's prefix (`type:`, `class:`, `account:`, `derived:`)."""

    TYPE    = ( 'Type'    , 'A rollup over all accounts of one account type.' )
    CLASS   = ( 'Class'   , 'A rollup over all accounts of one account class.' )
    ACCOUNT = ( 'Account' , 'A single account.' )
    DERIVED = ( 'Derived' , 'A figure derived across accounts (e.g. net worth).' )


class BooksDerivedFigure( LabeledEnum ):
    """A figure derived across accounts -- not a rollup of any one type/class/account."""

    NET_WORTH = ( 'Net Worth' , 'Total assets minus total liabilities.' )


# The class taxonomy enum for each type that has a class rung; Liability and Equity are absent.
_CLASS_ENUM_BY_TYPE = {
    AccountType.ASSET   : AssetClass,
    AccountType.REVENUE : IncomeTaxClass,
    AccountType.EXPENSE : ExpenseTaxClass,
}

# Types whose accounts are flow accounts: their columns read a per-period flow, not a balance.
_FLOW_TYPES = frozenset( ( AccountType.REVENUE, AccountType.EXPENSE ) )

# The order types appear in, and the types the default view suppresses (shown only on request).
_TYPE_DISPLAY_ORDER  = (
    AccountType.ASSET,
    AccountType.LIABILITY,
    AccountType.EQUITY,
    AccountType.REVENUE,
    AccountType.EXPENSE,
)
_DEFAULT_SUPPRESSED_TYPES = frozenset( ( AccountType.EQUITY, ) )

# The order value the engine-class fallback assigns its rungs and leaves: large, so a stamped placement
# (with small, input-derived orders) always sorts ahead of the fallback groups, which then keep their
# account order among themselves (a stable sort by order preserves first appearance for equal orders).
# Mirrors `_UNMAPPED_ORDER` in planning/display_placement.py -- the two must stay in lockstep.
_FALLBACK_ORDER = 10 ** 6


@dataclass( frozen = True )
class BooksColumnKey:
    """A column's opaque identity: a kind-prefixed token, e.g. `type:ASSET`, `class:ASSET:STOCKS`,
    `account:<uuid>`, `derived:NET_WORTH`. The token is the whole identity -- equality, hashing,
    and persistence are by its string. The typed accessors interpret it per kind (valid only for
    the matching kind); a token never seen in a catalog is simply dropped, never interpreted."""

    token : str

    @classmethod
    def for_type( cls, account_type : AccountType ) -> 'BooksColumnKey':
        return cls( f'{BooksColumnKind.TYPE}:{account_type.name}' )

    @classmethod
    def for_class( cls, account_type : AccountType, account_class : AccountClass ) -> 'BooksColumnKey':
        return cls( f'{BooksColumnKind.CLASS}:{account_type.name}:{account_class.name}' )

    @classmethod
    def for_account( cls, account_uuid : UUID ) -> 'BooksColumnKey':
        return cls( f'{BooksColumnKind.ACCOUNT}:{account_uuid}' )

    @classmethod
    def for_derived( cls, figure : BooksDerivedFigure ) -> 'BooksColumnKey':
        return cls( f'{BooksColumnKind.DERIVED}:{figure.name}' )

    @property
    def kind( self ) -> BooksColumnKind:
        return BooksColumnKind.from_name( self.token.split( ':', 1 )[ 0 ] )

    @property
    def account_type( self ) -> AccountType:
        """The type named by a `type:` or `class:` token."""
        type_name = self.token.split( ':' )[ 1 ]
        return AccountType[ type_name ]

    @property
    def account_class( self ) -> AccountClass:
        """The class named by a `class:` token (resolved within its type's taxonomy)."""
        _, type_name, class_name = self.token.split( ':', 2 )
        return _CLASS_ENUM_BY_TYPE[ AccountType[ type_name ] ][ class_name ]

    @property
    def account_uuid( self ) -> UUID:
        """The account identity carried by an `account:` token."""
        return UUID( self.token.split( ':', 1 )[ 1 ] )

    @property
    def derived_figure( self ) -> BooksDerivedFigure:
        """The figure named by a `derived:` token."""
        return BooksDerivedFigure[ self.token.split( ':', 1 )[ 1 ] ]

    def __str__( self ) -> str:
        return self.token


@dataclass( frozen = True )
class BooksColumn:
    """A column in a books' catalog: its identity, display label, and parent (the summary column
    it is a member of, or None for a top-level column)."""

    key        : BooksColumnKey
    label      : str
    parent_key : Optional[ BooksColumnKey ] = None

    @property
    def expandable( self ) -> bool:
        return False

    @property
    def account_uuid( self ) -> Optional[ UUID ]:
        """The account this column is, when it is a single-account column -- else None. The drill to
        an account's Journal applies only to account columns."""
        if self.key.kind == BooksColumnKind.ACCOUNT:
            return self.key.account_uuid
        return None


@dataclass( frozen = True )
class BooksLeafColumn( BooksColumn ):
    """A terminal column -- a single account or a derived figure. It cannot be drilled further."""


@dataclass( frozen = True )
class BooksSummaryColumn( BooksColumn ):
    """A rollup column -- a type or class total. Expanding it reveals its `member_keys` after it, the
    summary staying put as the group header (a type's classes, or its accounts where it has no class
    rung; a class's accounts)."""

    member_keys : tuple[ BooksColumnKey, ... ] = ()

    @property
    def expandable( self ) -> bool:
        return bool( self.member_keys )


def _key_tuple( tokens ) -> tuple:
    """A tuple of `BooksColumnKey`s from a list of stored tokens (empty for a missing/non-list value)."""
    return tuple( BooksColumnKey( str( token ) ) for token in tokens ) if isinstance( tokens, list ) else ()


def _subtree_block( catalog : 'BooksTableColumnCatalog', keys : list,
                    root_key : BooksColumnKey ) -> tuple[ int, int ]:
    """The half-open index range `[start, end)` a column and its descendants occupy in `keys`. In a
    well-formed (pre-order) frontier a column's descendants are exactly the run right after it, so the
    block is a column plus the contiguous descendants that follow."""
    start = keys.index( root_key )
    end   = start + 1
    while ( end < len( keys ) ) and catalog.descends_from( keys[ end ], root_key ):
        end += 1
        continue
    return start, end


def _present_anchor( catalog : 'BooksTableColumnCatalog', key : BooksColumnKey,
                     present : set ) -> Optional[ BooksColumnKey ]:
    """The frontier key a reveal of `key` anchors at: `key` itself when present, else the nearest ancestor
    that is -- a compressed single-child chain sits on the frontier as its top, so a drill aimed at the
    compressed terminal lands there. None when no ancestor is present."""
    while ( key is not None ) and ( key not in present ):
        column = catalog.get( key )
        key    = column.parent_key if column is not None else None
        continue
    return key


def _reveal_newcomers( catalog : 'BooksTableColumnCatalog', kept : list ) -> list:
    """`kept` with each already-expanded summary's newly-appeared catalog members inserted -- collapsed,
    at the summary's group tail. A summary is expanded when at least one of its immediate members is
    present (a collapsed one reveals nothing, keeping its members rolled up). Newcomers are never
    revisited (they are not added to the membership set), so they arrive collapsed for the user to
    expand. Insertion recomputes the group tail against the growing list, so nested expanded summaries
    stay contiguous."""
    present  = set( kept )
    revealed = list( kept )
    for summary_key in kept:
        column = catalog.get( summary_key )
        if not isinstance( column, BooksSummaryColumn ):
            continue
        if not any( member in present for member in column.member_keys ):
            continue
        newcomers = [ member for member in column.member_keys
                      if ( member in catalog ) and ( member not in present ) ]
        if not newcomers:
            continue
        end = _subtree_block( catalog, revealed, summary_key )[ 1 ]
        revealed[ end : end ] = newcomers
    return revealed


def _swap_sibling_blocks( catalog : 'BooksTableColumnCatalog', keys : list,
                          first_key : BooksColumnKey, second_key : BooksColumnKey ) -> list:
    """`keys` with the two columns' subtree blocks swapped -- each column carries its descendants. The
    blocks keep whatever lies between them, so adjacent siblings simply trade places, group and all."""
    first       = _subtree_block( catalog, keys, first_key )
    second      = _subtree_block( catalog, keys, second_key )
    left, right = ( first, second ) if first[ 0 ] < second[ 0 ] else ( second, first )
    return ( keys[ : left[ 0 ] ] + keys[ right[ 0 ] : right[ 1 ] ] + keys[ left[ 1 ] : right[ 0 ] ]
             + keys[ left[ 0 ] : left[ 1 ] ] + keys[ right[ 1 ] : ] )


@dataclass( frozen = True )
class BooksTableDefinition:
    """The view to render: the ordered frontier of columns, each shown or removed. A removed column
    keeps its place (rendered as a thin restore sliver) rather than leaving the table, so it stays at its
    natural position in the hierarchy. Expansion keeps the summary: an expanded summary stays as a group
    header, shown just before its members (group-header-first). Immutable: every operation returns a new
    definition, and the ones that consult column structure take the `catalog`. Persisted (per user) via
    `to_storage` / `from_storage`; fitted to a books with `adapt` before rendering."""

    column_keys : tuple[ BooksColumnKey, ... ] = ()
    # The subset of `column_keys` the user removed -- kept in place (rendered as a restore sliver) rather
    # than dropped, so a removed column holds its spot. A removed column is absorbed when its level is
    # collapsed into a parent that now represents it.
    removed_keys : tuple[ BooksColumnKey, ... ] = ()

    def to_storage( self ) -> dict:
        """This lens as a plain, storable value -- the ordered column tokens and which of them are
        removed. The definition owns its own storage form, so a store (the session) keeps no knowledge
        of column keys."""
        return { 'columns' : [ key.token for key in self.column_keys ],
                 'removed' : [ key.token for key in self.removed_keys ] }

    @classmethod
    def from_storage( cls, data ) -> Optional[ 'BooksTableDefinition' ]:
        """Rebuild a lens from a stored value, or None when absent. A bare list is a lens stored before
        removed columns were tracked (columns only). Unknown tokens survive parsing and are dropped
        later, when the lens is adapted to a books (`adapt`) -- so a stale token never breaks the read."""
        if isinstance( data, dict ):
            return cls( _key_tuple( data.get( 'columns' ) ), _key_tuple( data.get( 'removed' ) ) )
        if isinstance( data, list ):
            return cls( _key_tuple( data ) )
        return None

    def adapt( self, catalog : 'BooksTableColumnCatalog' ) -> 'BooksTableDefinition':
        """Fit to a books and reveal newcomers. First drop any column the run does not offer (an account
        that is not here, a class it lacks), preserving order; fall back to the default view if nothing
        survives. Then, under each already-expanded summary, reveal the catalog members that appeared
        after the lens was set -- added collapsed at the end of the group, so an account created by a
        later edit (e.g. a partner's income once the subject exists) surfaces without the user resetting
        the view. The removed set and the user's order/reordering are preserved, and the stored lens is
        left untouched (adapt-on-read)."""
        kept    = [ key for key in self.column_keys if key in catalog ]
        removed = tuple( key for key in self.removed_keys if key in catalog )
        if not kept:
            return catalog.default_definition()
        return BooksTableDefinition( tuple( _reveal_newcomers( catalog, kept ) ), removed )

    def expand( self, catalog : 'BooksTableColumnCatalog',
                key : Optional[ BooksColumnKey ] ) -> 'BooksTableDefinition':
        """Reveal a shown summary's members just after it -- the summary stays as the group header. Only
        members not already present are inserted. A compressed chain's terminal is not itself on the
        frontier (its single-child top is), so the reveal anchors at the nearest present ancestor and the
        members splice into the tree there. No-op if the column is removed, not an expandable summary, or
        already expanded."""
        if key in self.removed_keys:
            return self
        column = catalog.get( key )
        if not isinstance( column, BooksSummaryColumn ):
            return self
        present = set( self.column_keys )
        members = [ member_key for member_key in column.member_keys
                    if ( member_key in catalog ) and ( member_key not in present ) ]
        anchor  = _present_anchor( catalog, key, present )
        # No-op when there is nothing new to reveal, or -- the structural precondition -- when no ancestor
        # is on the frontier to anchor the splice to (an adapt-away can leave a key with no present chain).
        if ( not members ) or ( anchor is None ):
            return self
        expanded : list[ BooksColumnKey ] = []
        for frontier_key in self.column_keys:
            expanded.append( frontier_key )
            if frontier_key == anchor:
                expanded.extend( members )
            continue
        return BooksTableDefinition( tuple( expanded ), self.removed_keys )

    def collapse( self, catalog : 'BooksTableColumnCatalog',
                  key : Optional[ BooksColumnKey ] ) -> 'BooksTableDefinition':
        """Fold a summary's group back under it: drop every frontier descendant of the summary (shown or
        removed), the summary itself staying in place. A removed descendant is then represented by the
        summary, so it leaves the removed set. No-op for a non-summary column (no group to fold)."""
        column = catalog.get( key )
        if not isinstance( column, BooksSummaryColumn ):
            return self
        return BooksTableDefinition(
            tuple( frontier_key for frontier_key in self.column_keys
                   if not catalog.descends_from( frontier_key, key ) ),
            tuple( removed for removed in self.removed_keys
                   if not catalog.descends_from( removed, key ) ) )

    def remove( self, catalog : 'BooksTableColumnCatalog',
                key : Optional[ BooksColumnKey ] ) -> 'BooksTableDefinition':
        """Mark a shown column removed -- it keeps its place as a restore sliver. Removing a summary first
        collapses its group, so an expanded group leaves a single sliver at the summary's position rather
        than one per member. No-op if it is not a shown column."""
        if ( key not in self.column_keys ) or ( key in self.removed_keys ):
            return self
        folded = self.collapse( catalog, key )
        return BooksTableDefinition( folded.column_keys, folded.removed_keys + ( key, ) )

    def restore( self, key : Optional[ BooksColumnKey ] ) -> 'BooksTableDefinition':
        """Bring a removed column back into view -- clear it from the removed set, in its place."""
        return BooksTableDefinition(
            self.column_keys,
            tuple( removed for removed in self.removed_keys if removed != key ) )

    def move( self, catalog : 'BooksTableColumnCatalog',
              key : Optional[ BooksColumnKey ], offset : int ) -> 'BooksTableDefinition':
        """Reorder a column among its siblings by `offset` (-1 left, +1 right), carrying its whole
        subtree: it swaps with the adjacent sibling under the same parent (an expanded summary takes its
        members along), keeping the frontier a well-formed tree. No-op at a group edge (no sibling that
        way) or for an absent column -- a column never leaves its parent's group."""
        keys   = list( self.column_keys )
        column = catalog.get( key )
        if ( key not in keys ) or ( column is None ):
            return self
        siblings = [ frontier_key for frontier_key in keys
                     if catalog.get( frontier_key )
                     and ( catalog.get( frontier_key ).parent_key == column.parent_key ) ]
        target = siblings.index( key ) + offset
        if ( target < 0 ) or ( target >= len( siblings ) ):
            return self
        reordered = _swap_sibling_blocks( catalog, keys, key, siblings[ target ] )
        return BooksTableDefinition( tuple( reordered ), self.removed_keys )


class BooksTableColumnCatalog:
    """Every column a given books offers -- the source of truth for what may be shown, drilled,
    or added, and for the default view. Built once from a `Chart`; looked up by `BooksColumnKey`."""

    def __init__( self, columns : list[ BooksColumn ] ):
        self._columns = tuple( columns )
        self._by_key  = { column.key : column for column in self._columns }

    @classmethod
    def build( cls, chart : Chart ) -> 'BooksTableColumnCatalog':
        """Walk the chart into the full column set: a derived column per figure, then per type its
        rollup and the rollup rungs its accounts display under (an account's `display_placement`, or its
        engine class as the fallback), down to an account column per displayable account. Roots and
        valuation companions are not columns."""
        columns : list[ BooksColumn ] = []
        for figure in BooksDerivedFigure:
            columns.append( BooksLeafColumn(
                key = BooksColumnKey.for_derived( figure ), label = figure.label ) )
        for account_type in _TYPE_DISPLAY_ORDER:
            cls._append_type( columns, chart, account_type )
            continue
        return cls( columns )

    @classmethod
    def _append_type( cls, columns : list[ BooksColumn ], chart : Chart,
                      account_type : AccountType ) -> None:
        """Build a type's subtree from its accounts' display placements: each account descends through
        its rollup rungs (created on first appearance), landing as a leaf under its deepest rung. A rung's
        members are ordered by their placement order (a stable sort, so equal orders keep account order),
        placing input-grouped columns as the inputs present them and the engine-class fallback after them.
        A type with a class rung omits a placeless account (as its fallback would leave it), matching the
        columns the chart offers."""
        type_key    = BooksColumnKey.for_type( account_type )
        has_classes = account_type in _CLASS_ENUM_BY_TYPE
        group_parent : dict[ str, tuple ] = {}   # group token -> (AccountDisplayGroup, parent key)
        group_members : dict[ str, list ] = {}   # group token -> its members, each (key, order)
        type_members : list[ tuple ] = []        # the type's members, each (key, order)
        for account in cls._displayable_accounts( chart, account_type ):
            placement = cls._placement_of( account )
            if has_classes and not placement.path:
                continue
            parent_key     = type_key
            parent_members = type_members
            path_tokens : list[ str ] = []
            for group in placement.path:
                path_tokens.append( group.key )
                group_key = cls._group_key( account_type, path_tokens )
                if group_key.token not in group_parent:
                    group_parent[ group_key.token ]  = ( group, parent_key )
                    group_members[ group_key.token ] = []
                    parent_members.append( ( group_key, group.order ) )
                parent_key     = group_key
                parent_members = group_members[ group_key.token ]
                continue
            account_key = BooksColumnKey.for_account( account.account_uuid )
            columns.append( BooksLeafColumn(
                key = account_key, label = account.name, parent_key = parent_key ) )
            parent_members.append( ( account_key, placement.order ) )
            continue
        for token, ( group, parent_key ) in group_parent.items():
            columns.append( BooksSummaryColumn(
                key = BooksColumnKey( token ), label = group.label, parent_key = parent_key,
                member_keys = cls._ordered_keys( group_members[ token ] ) ) )
            continue
        columns.append( BooksSummaryColumn(
            key = type_key, label = account_type.label,
            member_keys = cls._ordered_keys( type_members ) ) )
        return

    @staticmethod
    def _ordered_keys( members : list ) -> tuple:
        """The member keys sorted by placement order -- a stable sort, so members of equal order keep the
        account order they were seen in (which is what the engine-class fallback relies on)."""
        return tuple( key for key, _order in sorted( members, key = lambda member: member[ 1 ] ) )

    @staticmethod
    def _displayable_accounts( chart : Chart, account_type : AccountType ) -> list:
        """The accounts of `account_type` that get a column -- every account but the type root and the
        valuation companions (whose appreciation a holding's market value already carries)."""
        return [ account for account in chart.accounts( account_type = account_type )
                 if ( not account.is_root ) and ( not account.is_valuation ) ]

    @classmethod
    def _placement_of( cls, account ) -> AccountDisplayPlacement:
        """An account's display placement: its stamped `display_placement`, or the engine-class fallback
        when it carries none."""
        if account.display_placement is not None:
            return account.display_placement
        return cls._engine_class_placement( account )

    @staticmethod
    def _engine_class_placement( account ) -> AccountDisplayPlacement:
        """The fallback placement: a single rung named by the account's engine class (asset, income, or
        expense), or no rung when it has none -- reproducing the chart's own class grouping."""
        account_class = ( account.asset_class or account.income_tax_class or account.expense_tax_class )
        if account_class is None:
            return AccountDisplayPlacement( order = _FALLBACK_ORDER )
        group = AccountDisplayGroup( key = account_class.name, label = account_class.label,
                                     order = _FALLBACK_ORDER )
        return AccountDisplayPlacement( path = ( group, ), order = _FALLBACK_ORDER )

    @staticmethod
    def _group_key( account_type : AccountType, path_tokens : list ) -> BooksColumnKey:
        """A rollup rung's column key: its type and the group keys down to it. A single-rung fallback
        keys as `class:TYPE:CLASSNAME` -- the engine-class column key -- so the fallback view is exactly
        the chart's class grouping."""
        return BooksColumnKey(
            f'{BooksColumnKind.CLASS}:{account_type.name}:{"/".join( path_tokens )}' )

    def columns( self ) -> tuple[ BooksColumn, ... ]:
        return self._columns

    def get( self, key : BooksColumnKey ) -> Optional[ BooksColumn ]:
        return self._by_key.get( key )

    def __contains__( self, key : BooksColumnKey ) -> bool:
        return key in self._by_key

    def members( self, column : BooksSummaryColumn ) -> list[ BooksColumn ]:
        """The columns a summary expands into -- its members that this books actually has."""
        return [ self._by_key[ key ] for key in column.member_keys if key in self._by_key ]

    def descends_from( self, key : BooksColumnKey, ancestor : BooksColumnKey ) -> bool:
        """Whether `ancestor` is on `key`'s parent chain -- how a collapse finds the columns to
        fold back into a parent."""
        column = self.get( key )
        while ( column is not None ) and ( column.parent_key is not None ):
            if column.parent_key == ancestor:
                return True
            column = self.get( column.parent_key )
            continue
        return False

    def default_definition( self ) -> BooksTableDefinition:
        """The starting view: each derived figure, then one rollup per non-suppressed type
        (Equity is suppressed). The figures lead, as the headline summaries."""
        keys = [ BooksColumnKey.for_derived( figure ) for figure in BooksDerivedFigure ]
        for account_type in _TYPE_DISPLAY_ORDER:
            if account_type in _DEFAULT_SUPPRESSED_TYPES:
                continue
            keys.append( BooksColumnKey.for_type( account_type ) )
            continue
        return BooksTableDefinition( tuple( keys ) )


@dataclass( frozen = True )
class BooksTableColumn:
    """One column as rendered. `column` is what it displays -- normally the frontier column, but for a
    single-child chain (a rung whose one member would duplicate its value) the chain's terminal, with the
    absorbed rungs' labels in `breadcrumb`. `op_key` is the key structural ops (move / remove / collapse)
    act on -- the top of the chain -- while `expand_key` is the terminal, so drilling deeper still works.
    `removed` marks a restore sliver; `can_expand` / `can_collapse` gate those controls;
    `depth` / `group` drive the tint; `can_move_*` gate the reorder arrows at a group edge (a reorder is a
    within-group sibling swap)."""
    column         : BooksColumn
    op_key         : BooksColumnKey
    expand_key     : BooksColumnKey
    removed        : bool  = False
    can_expand     : bool  = False
    can_collapse   : bool  = False
    depth          : int   = 0
    group          : str   = ''
    can_move_left  : bool  = False
    can_move_right : bool  = False
    breadcrumb     : tuple = ()


@dataclass( frozen = True )
class BooksTableCell:
    column  : BooksColumn
    value   : Optional[ Decimal ]   # None for a removed column's sliver -- no figure is shown
    removed : bool = False


@dataclass( frozen = True )
class BooksTableRow:
    span  : DateSpan
    cells : tuple[ BooksTableCell, ... ]


@dataclass( frozen = True )
class BooksTable:
    """A rendered table: the frontier columns (some shown as thin restore slivers) and a row per period,
    each carrying a cell per column."""

    columns : tuple[ BooksTableColumn, ... ]
    rows    : tuple[ BooksTableRow, ... ]


def _column_depth( catalog : BooksTableColumnCatalog, key : BooksColumnKey ) -> int:
    """How many levels down from its top-level group a column sits: a type or derived figure is 0, a
    class 1, an account 1 or 2 (by whether its type has a class rung). The view lightens the tint by it."""
    depth  = 0
    column = catalog.get( key )
    while ( column is not None ) and ( column.parent_key is not None ):
        depth += 1
        column = catalog.get( column.parent_key )
        continue
    return depth


def _column_group( catalog : BooksTableColumnCatalog, key : BooksColumnKey ) -> str:
    """A slug for the column's top-level group -- its account type (`asset`, `expense`, ...) or, for a
    derived figure, the figure (`net-worth`). Every column in a group shares it, so the view can tint a
    whole group with one hue."""
    column = catalog.get( key )
    while ( column is not None ) and ( column.parent_key is not None ):
        column = catalog.get( column.parent_key )
        continue
    top = column.key
    if top.kind == BooksColumnKind.DERIVED:
        return top.derived_figure.name.lower().replace( '_', '-' )
    return top.account_type.name.lower()


def _sibling_order( catalog : BooksTableColumnCatalog,
                    keys : tuple[ BooksColumnKey, ... ] ) -> dict:
    """Each present column's position among its siblings, as `{ key : (index, sibling_count) }`. Siblings
    are the frontier columns sharing a parent (top-level columns share the None parent). Used to tell,
    per column, whether a reorder has somewhere to go in each direction."""
    by_parent : dict = {}
    for key in keys:
        column = catalog.get( key )
        if column is not None:
            by_parent.setdefault( column.parent_key, [] ).append( key )
            continue
    return { key : ( group.index( key ), len( group ) )
             for group in by_parent.values() for key in group }


def _compressible( catalog : BooksTableColumnCatalog, key : BooksColumnKey ) -> bool:
    """A single-child grouping rung that adds no information: a summary with exactly one member, below a
    type root. It duplicates that member's value, so the chain shows as its terminal (path compression). A
    type root (parent-less) is exempt -- the top-level total stays a column even when it has one child."""
    column = catalog.get( key )
    return ( isinstance( column, BooksSummaryColumn ) and ( len( column.member_keys ) == 1 )
             and ( column.parent_key is not None ) )


def _chain_bottom( catalog : BooksTableColumnCatalog, key : BooksColumnKey ) -> tuple:
    """Walk down from `key` through compressible single-child rungs to the chain terminal -- the first
    descendant that is a leaf or a genuinely branching (multi-member) summary -- collecting the absorbed
    rungs' labels top-down. The chain thus renders as its terminal alone: a leaf keeps its account (its
    Journal reachable while collapsed, no dead-end expand), a branching summary keeps its own expand."""
    labels : list = []
    while _compressible( catalog, key ):
        labels.append( catalog.get( key ).label )
        key = catalog.get( key ).member_keys[ 0 ]
        continue
    return key, tuple( labels )


def _absorbed( catalog : BooksTableColumnCatalog, key : BooksColumnKey, shown : set ) -> bool:
    """`key` is already carried by a shown compressible ancestor: its parent is a shown single-child rung,
    so the whole chain renders once, at that ancestor's position -- this member is skipped here."""
    parent = catalog.get( key ).parent_key
    return ( parent is not None ) and ( parent in shown ) and _compressible( catalog, parent )


def _render_columns( catalog : BooksTableColumnCatalog,
                     definition : BooksTableDefinition ) -> tuple[ BooksTableColumn, ... ]:
    """Resolve the frontier to rendered columns. A single-child chain (a rung whose one member would
    duplicate its value, recursively) renders as its terminal alone -- carrying the absorbed rungs as a
    breadcrumb, structural ops pointed at the chain top and drill-in at the terminal -- so it never offers
    a dead-end expand and a terminal account stays reachable while collapsed. Every other column renders
    itself. Each carries removed state, expand/collapse availability, tint depth/group, and sibling-move
    reach. Keys absent from the catalog are skipped (callers adapt first)."""
    removed   = set( definition.removed_keys )
    frontier  = set( definition.column_keys )
    shown     = { key for key in definition.column_keys if ( key in catalog ) and ( key not in removed ) }
    positions = _sibling_order( catalog, definition.column_keys )
    rendered : list[ BooksTableColumn ] = []
    for key in definition.column_keys:
        if key not in catalog:
            continue
        is_removed = key in removed
        if ( not is_removed ) and _absorbed( catalog, key, shown ):
            continue                                   # rendered by its single-child ancestor's column
        terminal, breadcrumb = ( key, () ) if is_removed else _chain_bottom( catalog, key )
        column       = catalog.get( terminal )
        breadcrumb   = tuple( label for label in breadcrumb if label != column.label )
        expanded     = column.expandable and any( member in frontier for member in column.member_keys )
        index, count = positions[ key ]
        rendered.append( BooksTableColumn(
            column         = column,
            op_key         = key,
            expand_key     = terminal,
            removed        = is_removed,
            can_expand     = ( not is_removed ) and column.expandable and ( not expanded ),
            can_collapse   = ( not is_removed ) and expanded,
            depth          = _column_depth( catalog, key ),
            group          = _column_group( catalog, key ),
            can_move_left  = index > 0,
            can_move_right = index < count - 1,
            breadcrumb     = breadcrumb ) )
        continue
    return tuple( rendered )


def build_books_table( ledger : Ledger, chart : Chart, spans : list[ DateSpan ],
                       definition : BooksTableDefinition,
                       catalog : BooksTableColumnCatalog ) -> BooksTable:
    """Render `definition` over `spans`: resolve each frontier key to its rendered column and compute its
    per-period cell -- except a removed column, which renders as a value-less restore sliver."""
    columns = _render_columns( catalog, definition )
    rows    = tuple(
        BooksTableRow(
            span  = span,
            cells = tuple(
                BooksTableCell(
                    rendered.column,
                    None if rendered.removed
                    else _column_value( catalog, rendered.column, ledger, chart, span ),
                    rendered.removed )
                for rendered in columns ) )
        for span in spans
    )
    return BooksTable( columns = columns, rows = rows )


def _account_leaf_keys( catalog : BooksTableColumnCatalog, key : BooksColumnKey ) -> list:
    """The account-leaf keys under a column: the column itself if it is a leaf, else every account leaf
    beneath its rungs. A rollup's figure is the sum over these, so a group totals its members whatever
    axis groups them (an engine class or an input category)."""
    column = catalog.get( key )
    if isinstance( column, BooksSummaryColumn ):
        leaves : list = []
        for member in column.member_keys:
            leaves.extend( _account_leaf_keys( catalog, member ) )
            continue
        return leaves
    return [ key ]


def _column_value( catalog : BooksTableColumnCatalog, column : BooksColumn,
                   ledger : Ledger, chart : Chart, span : DateSpan ) -> Decimal:
    """A column's figure for one period: a summary sums its account leaves (so market value and flows
    fold in exactly as a type/class total would); a leaf reads its own figure."""
    if isinstance( column, BooksSummaryColumn ):
        return sum( ( _cell_value( leaf, ledger, chart, span )
                      for leaf in _account_leaf_keys( catalog, column.key ) ), Decimal( '0' ) )
    return _cell_value( column.key, ledger, chart, span )


def _cell_value( key : BooksColumnKey, ledger : Ledger, chart : Chart, span : DateSpan ) -> Decimal:
    """A leaf column's figure for one period: the derived figure, or an account's flow over the span
    (revenue/expense) or balance at span end (assets at market value, else natural balance)."""
    if key.kind == BooksColumnKind.DERIVED:
        if key.derived_figure == BooksDerivedFigure.NET_WORTH:
            return ledger.net_worth( through = span.end_date )
        raise ValueError( f'Unsupported derived figure: {key.derived_figure}' )
    account = chart.account_by_uuid( key.account_uuid )
    if account is None:
        return Decimal( '0' )
    if account.effective_account_type in _FLOW_TYPES:
        return ledger.natural_flow( account, start = span.start_date, end = span.end_date )
    if account.effective_account_type == AccountType.ASSET:
        return ledger.market_value( account, through = span.end_date )
    return ledger.natural_balance( account, through = span.end_date )
