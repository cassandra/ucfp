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
        return dict( data )

    if data is None:
        return None
    if isinstance( target_type, type ):
        if issubclass( target_type, Enum ):
            return target_type[ data ]
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


def _from_dataclass( target_type: Any, data: dict ) -> Any:
    hints = get_type_hints( target_type )
    kwargs = { name: from_json_data( hints[ name ], value )
               for name, value in data.items() if name in hints }
    return target_type( **kwargs )
