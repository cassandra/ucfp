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
    """A figure derived across accounts -- not a rollup of any one type/class/account. The
    catalog of derived columns; small and extensible (Net Worth is the only one today)."""

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
    it is a member of, or None for a top-level column). The base of summary and leaf columns."""

    key        : BooksColumnKey
    label      : str
    parent_key : Optional[ BooksColumnKey ] = None

    @property
    def expandable( self ) -> bool:
        return False


@dataclass( frozen = True )
class BooksLeafColumn( BooksColumn ):
    """A terminal column -- a single account or a derived figure. It cannot be drilled further."""


@dataclass( frozen = True )
class BooksSummaryColumn( BooksColumn ):
    """A rollup column -- a type or class total. Expanding it replaces it with its `member_keys`
    (a type's classes, or its accounts where it has no class rung; a class's accounts)."""

    member_keys : tuple[ BooksColumnKey, ... ] = ()

    @property
    def expandable( self ) -> bool:
        return bool( self.member_keys )


@dataclass( frozen = True )
class BooksTableDefinition:
    """The view to render: the ordered, visible column keys. Expansion state is implicit -- an
    expanded type is simply absent while its class keys are present. Persisted (per user) as the
    list of tokens; adapted to a books before rendering (see `adapt`)."""

    column_keys : tuple[ BooksColumnKey, ... ] = ()

    def tokens( self ) -> list[ str ]:
        return [ key.token for key in self.column_keys ]

    @classmethod
    def from_tokens( cls, tokens : list[ str ] ) -> 'BooksTableDefinition':
        return cls( tuple( BooksColumnKey( token ) for token in tokens ) )


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
                    member_keys = tuple( BooksColumnKey.for_account( a.account_uuid ) for a in accounts ) ) )
                member_keys.append( class_key )
                continue
        else:
            accounts = [ account for account in chart.accounts( account_type = account_type )
                         if ( not account.is_root ) and ( not account.is_valuation ) ]
            cls._append_accounts( columns, accounts, parent_key = type_key )
            member_keys = [ BooksColumnKey.for_account( a.account_uuid ) for a in accounts ]
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


def adapt( definition : BooksTableDefinition,
           catalog : BooksTableColumnCatalog ) -> BooksTableDefinition:
    """Fit a stored definition to a books: drop any column the books does not offer (an account
    that is not here, a class it lacks), preserving order. If nothing survives, fall back to the
    default view. Adaptation only drops -- it never resurrects a deliberately hidden column."""
    kept = tuple( key for key in definition.column_keys if key in catalog )
    if not kept:
        return catalog.default_definition()
    return BooksTableDefinition( kept )


@dataclass( frozen = True )
class BooksTableCell:
    column : BooksColumn
    value  : Decimal


@dataclass( frozen = True )
class BooksTableRow:
    span  : DateSpan
    cells : tuple[ BooksTableCell, ... ]


@dataclass( frozen = True )
class BooksTable:
    """A rendered table: the visible columns and a row per period, each carrying a cell per
    column."""

    columns : tuple[ BooksColumn, ... ]
    rows    : tuple[ BooksTableRow, ... ]


def build_books_table( ledger : Ledger, chart : Chart, spans : list[ DateSpan ],
                       definition : BooksTableDefinition,
                       catalog : BooksTableColumnCatalog ) -> BooksTable:
    """Render `definition` over `spans`: resolve each visible key to its catalog column and
    compute its per-period cell. Keys absent from the catalog are skipped (callers adapt first)."""
    columns = tuple( catalog.get( key ) for key in definition.column_keys if key in catalog )
    rows    = tuple(
        BooksTableRow(
            span  = span,
            cells = tuple( BooksTableCell( column, _cell_value( column.key, ledger, chart, span ) )
                           for column in columns ) )
        for span in spans
    )
    return BooksTable( columns = columns, rows = rows )


def _cell_value( key : BooksColumnKey, ledger : Ledger, chart : Chart, span : DateSpan ) -> Decimal:
    """One column's figure for one period: a flow over the span for revenue/expense, a balance at
    span end otherwise (assets at market value)."""
    if key.kind == BooksColumnKind.DERIVED:
        return ledger.net_worth( through = span.end_date )
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
