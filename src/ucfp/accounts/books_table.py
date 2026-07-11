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
        """Fit to a books: drop any column it does not offer (an account that is not here, a class it
        lacks), preserving order. Fall back to the default view if nothing survives. Both the frontier
        and the removed subset are filtered, so the removed set stays within the frontier."""
        kept    = tuple( key for key in self.column_keys if key in catalog )
        removed = tuple( key for key in self.removed_keys if key in catalog )
        if not kept:
            return catalog.default_definition()
        return BooksTableDefinition( kept, removed )

    def expand( self, catalog : 'BooksTableColumnCatalog',
                key : Optional[ BooksColumnKey ] ) -> 'BooksTableDefinition':
        """Reveal a shown summary's members just after it -- the summary stays as the group header. Only
        members not already present are inserted. No-op if the column is removed, not an expandable
        summary, or already expanded."""
        if key in self.removed_keys:
            return self
        column = catalog.get( key )
        if not isinstance( column, BooksSummaryColumn ):
            return self
        present = set( self.column_keys )
        members = [ member_key for member_key in column.member_keys
                    if ( member_key in catalog ) and ( member_key not in present ) ]
        if not members:
            return self
        expanded : list[ BooksColumnKey ] = []
        for frontier_key in self.column_keys:
            expanded.append( frontier_key )
            if frontier_key == key:
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
        rollup, its class rollups (where it has a class rung), and an account column per displayable
        account. Roots and valuation companions are not columns."""
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
        type_key = BooksColumnKey.for_type( account_type )
        if account_type in _CLASS_ENUM_BY_TYPE:
            member_keys = []
            for account_class in chart.classes( account_type ):
                class_key = BooksColumnKey.for_class( account_type, account_class )
                accounts  = chart.accounts( account_class = account_class )
                cls._append_accounts( columns, accounts, parent_key = class_key )
                columns.append( BooksSummaryColumn(
                    key = class_key, label = account_class.label, parent_key = type_key,
                    member_keys = tuple(
                        BooksColumnKey.for_account( account.account_uuid ) for account in accounts ) ) )
                member_keys.append( class_key )
                continue
        else:
            accounts = [ account for account in chart.accounts( account_type = account_type )
                         if ( not account.is_root ) and ( not account.is_valuation ) ]
            cls._append_accounts( columns, accounts, parent_key = type_key )
            member_keys = [ BooksColumnKey.for_account( account.account_uuid ) for account in accounts ]
        columns.append( BooksSummaryColumn(
            key = type_key, label = account_type.label, member_keys = tuple( member_keys ) ) )
        return

    @staticmethod
    def _append_accounts( columns : list[ BooksColumn ], accounts : list,
                          parent_key : BooksColumnKey ) -> None:
        for account in accounts:
            columns.append( BooksLeafColumn(
                key = BooksColumnKey.for_account( account.account_uuid ),
                label = account.name, parent_key = parent_key ) )
            continue
        return

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
    """One column as rendered: its catalog column, whether it is currently removed (a thin restore sliver
    rather than a full column with its figures), whether it is an expanded summary (its members shown
    alongside it), the structural facts the view tints by -- the drill `depth` and top-level `group` --
    and whether it has a sibling to trade places with in each direction (a reorder is a within-group
    sibling swap, so an edge column offers no move that way)."""
    column         : BooksColumn
    removed        : bool = False
    expanded       : bool = False
    depth          : int  = 0
    group          : str  = ''
    can_move_left  : bool = False
    can_move_right : bool = False


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


def _render_columns( catalog : BooksTableColumnCatalog,
                     definition : BooksTableDefinition ) -> tuple[ BooksTableColumn, ... ]:
    """Resolve the frontier to rendered columns, each carrying its removed state, whether it is an
    expanded summary (a member of it is present), its drill depth and top-level group (what the view
    tints by), and whether it has a sibling to move toward in each direction. Keys absent from the
    catalog are skipped (callers adapt first)."""
    removed   = set( definition.removed_keys )
    frontier  = set( definition.column_keys )
    positions = _sibling_order( catalog, definition.column_keys )
    rendered : list[ BooksTableColumn ] = []
    for key in definition.column_keys:
        if key not in catalog:
            continue
        column       = catalog.get( key )
        expanded     = ( isinstance( column, BooksSummaryColumn )
                         and any( member in frontier for member in column.member_keys ) )
        index, count = positions[ key ]
        rendered.append( BooksTableColumn(
            column         = column,
            removed        = key in removed,
            expanded       = expanded,
            depth          = _column_depth( catalog, key ),
            group          = _column_group( catalog, key ),
            can_move_left  = index > 0,
            can_move_right = index < count - 1 ) )
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
                    None if rendered.removed else _cell_value( rendered.column.key, ledger, chart, span ),
                    rendered.removed )
                for rendered in columns ) )
        for span in spans
    )
    return BooksTable( columns = columns, rows = rows )


def _cell_value( key : BooksColumnKey, ledger : Ledger, chart : Chart, span : DateSpan ) -> Decimal:
    """One column's figure for one period: a flow over the span for revenue/expense, a balance at
    span end otherwise (assets at market value)."""
    if key.kind == BooksColumnKind.DERIVED:
        if key.derived_figure == BooksDerivedFigure.NET_WORTH:
            return ledger.net_worth( through = span.end_date )
        raise ValueError( f'Unsupported derived figure: {key.derived_figure}' )
    if key.kind == BooksColumnKind.TYPE:
        if key.account_type in _FLOW_TYPES:
            return ledger.type_flow( key.account_type, start = span.start_date, end = span.end_date )
        return ledger.type_total( key.account_type, through = span.end_date )
    if key.kind == BooksColumnKind.CLASS:
        if key.account_type in _FLOW_TYPES:
            return ledger.class_flow( key.account_class, start = span.start_date, end = span.end_date )
        return ledger.class_total( key.account_class, through = span.end_date )
    account = chart.account_by_uuid( key.account_uuid )
    if account is None:
        return Decimal( '0' )
    if account.effective_account_type in _FLOW_TYPES:
        return ledger.natural_flow( account, start = span.start_date, end = span.end_date )
    if account.effective_account_type == AccountType.ASSET:
        return ledger.market_value( account, through = span.end_date )
    return ledger.natural_balance( account, through = span.end_date )
