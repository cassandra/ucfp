"""Generic JSON (de)serialization for frozen-dataclass aggregates.

Maps a typed aggregate -- nested frozen dataclasses, with `Decimal` / `date` / `Enum` and
value objects like `Rate` / `Duration` as leaves -- to and from JSON-safe primitives, so a
persisted JSON document is exactly the serialized form of a typed object and nothing else
handles raw dicts.

`to_json_data` is value-driven; `from_json_data` is type-driven, reconstructing against the
target dataclass's annotations. Supported leaves: str / int / float / bool / None, `Decimal`
(<-> str, lossless), `date` (<-> ISO 8601), `Enum` (<-> member name); containers: dataclass,
list, tuple, dict; typing: `Optional` / Union-with-None. An unsupported type raises
TypeError rather than silently passing a value that will not round-trip.
"""
import dataclasses
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints

_NoneType = type( None )


class DataclassJsonError( Exception ):
    """Stored JSON does not match its target dataclass -- typically a record written under an older
    schema (a field added, removed, or renamed since it was saved)."""


def to_json_data( obj: Any ) -> Any:
    if obj is None:
        return None
    if isinstance( obj, Enum ):
        return obj.name
    if isinstance( obj, bool ):
        return obj
    if isinstance( obj, ( int, float, str ) ):
        return obj
    if isinstance( obj, Decimal ):
        return str( obj )
    if isinstance( obj, date ):
        return obj.isoformat()
    if dataclasses.is_dataclass( obj ) and not isinstance( obj, type ):
        return { f.name: to_json_data( getattr( obj, f.name ) )
                 for f in dataclasses.fields( obj ) }
    if isinstance( obj, ( list, tuple ) ):
        return [ to_json_data( item ) for item in obj ]
    if isinstance( obj, dict ):
        return { key: to_json_data( value ) for key, value in obj.items() }
    raise TypeError( f'Cannot serialize value of type {type( obj ).__name__!r}.' )


def from_json_data( target_type: Any, data: Any ) -> Any:
    origin = get_origin( target_type )

    if origin is Union:
        return _from_union( get_args( target_type ), data )
    if origin in ( list, tuple ):
        return _from_sequence( origin, get_args( target_type ), data )
    if origin is dict:
        args = get_args( target_type )
        if not args:
            return dict( data )
        key_type, value_type = args
        return { from_json_data( key_type, key ): from_json_data( value_type, value )
                 for key, value in data.items() }

    if data is None:
        return None
    if isinstance( target_type, type ):
        if issubclass( target_type, Enum ):
            return _from_enum( target_type, data )
        if issubclass( target_type, Decimal ):
            return Decimal( data )
        if issubclass( target_type, date ):
            return date.fromisoformat( data )
        if dataclasses.is_dataclass( target_type ):
            return _from_dataclass( target_type, data )
    return data


def _from_union( args: tuple, data: Any ) -> Any:
    if data is None:
        return None
    non_none = [ arg for arg in args if arg is not _NoneType ]
    if len( non_none ) == 1:
        return from_json_data( non_none[ 0 ], data )
    raise TypeError( f'Cannot deserialize an ambiguous Union of {non_none}.' )


def _from_sequence( origin: Any, args: tuple, data: Any ) -> Any:
    if origin is list:
        ( element_type, ) = args
        return [ from_json_data( element_type, item ) for item in data ]
    if len( args ) == 2 and args[ 1 ] is Ellipsis:
        return tuple( from_json_data( args[ 0 ], item ) for item in data )
    return tuple( from_json_data( arg, item ) for arg, item in zip( args, data ) )


def _from_enum( target_type: Any, data: Any ) -> Any:
    try:
        return target_type[ data ]
    except KeyError as error:
        raise DataclassJsonError(
            f'{data!r} is not a member of {target_type.__name__} -- the stored value may predate a '
            f'schema change (a member removed or renamed since it was saved).' ) from error


def _from_dataclass( target_type: Any, data: dict ) -> Any:
    hints = get_type_hints( target_type )
    kwargs = { name: from_json_data( hints[ name ], value )
               for name, value in data.items() if name in hints }
    try:
        return target_type( **kwargs )
    except TypeError as error:
        raise DataclassJsonError(
            f'Cannot build {target_type.__name__} from stored data: {error}. The record may '
            f'predate a schema change -- stored fields {sorted( data )}, '
            f'expected {sorted( hints )}.' ) from error
