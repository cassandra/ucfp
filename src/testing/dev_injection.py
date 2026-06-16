import json
import logging
import os
import tempfile

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class DevInjectionManager:
    """
    External data injection for development / UI testing.

    Pokes named override payloads into a shared store -- either the Django
    cache (fast) or a JSON file under ``DATA_DIR`` (survives the dev server's
    auto-reload) -- that DEBUG-gated code paths read back via ``get_override()``
    / ``inject_override_if_available()``. This lets you force a specific
    response or state for frontend testing without touching real data or
    restarting the server. Requires ``DEBUG = True``; every operation is a
    no-op otherwise.

    Drive it from the command line:
        python manage.py dev_inject <name> '{"...": "..."}'    # inject (file)
        python manage.py dev_inject <name> '{...}' --cache     # inject (cache)
        python manage.py dev_inject <name> '{...}' --persistent
        python manage.py dev_inject --list
        python manage.py dev_inject --clear

    Read it at an injection point in your own code:
        if settings.DEBUG:
            DevInjectionManager.inject_override_if_available('<name>', data, '<key>')
    """

    CACHE_PREFIX = 'dev_inject_'
    # Django's cache API cannot enumerate keys, so the names of cache-stored
    # overrides are tracked here (the file store is enumerated via the FS).
    CACHE_INDEX_KEY = 'dev_inject__index__'
    ONE_TIME_CACHE_TIMEOUT_SECS = 300
    DATA_DIR = os.path.join( tempfile.gettempdir(), 'dev_overrides' )

    # -- storage helpers ---------------------------------------------------

    @classmethod
    def _ensure_data_dir( cls ):
        if not os.path.exists( cls.DATA_DIR ):
            os.makedirs( cls.DATA_DIR, exist_ok = True )

    @classmethod
    def _get_file_path( cls, name ):
        cls._ensure_data_dir()
        return os.path.join( cls.DATA_DIR, f'{name}.json' )

    @classmethod
    def _cache_index( cls ):
        return set( cache.get( cls.CACHE_INDEX_KEY ) or [] )

    @classmethod
    def _cache_index_add( cls, name ):
        names = cls._cache_index()
        names.add( name )
        cache.set( cls.CACHE_INDEX_KEY, list( names ), timeout = None )

    @classmethod
    def _cache_index_remove( cls, name ):
        names = cls._cache_index()
        names.discard( name )
        cache.set( cls.CACHE_INDEX_KEY, list( names ), timeout = None )

    # -- write side --------------------------------------------------------

    @classmethod
    def inject( cls, name, payload, one_time = True, use_cache = False ):
        """
        Store ``payload`` (any JSON-serializable value) under ``name``. When
        ``one_time``, it is consumed on the first read; otherwise it persists
        until cleared. ``use_cache`` stores in the Django cache instead of a
        file. Returns True on success, False outside DEBUG or on write error.
        """
        if not settings.DEBUG:
            return False

        entry = { 'data': payload, 'one_time': one_time }

        if use_cache:
            timeout = cls.ONE_TIME_CACHE_TIMEOUT_SECS if one_time else None
            cache.set( f'{cls.CACHE_PREFIX}{name}', entry, timeout = timeout )
            cls._cache_index_add( name )
            logger.info( 'DevInjection: cached override %r (one_time=%s)', name, one_time )
            return True

        try:
            with open( cls._get_file_path( name ), 'w' ) as f:
                json.dump( entry, f, indent = 2 )
        except IOError as e:
            logger.error( 'DevInjection: failed to write override %r: %s', name, e )
            return False
        logger.info( 'DevInjection: wrote override %r to file (one_time=%s)', name, one_time )
        return True

    # -- read side ---------------------------------------------------------

    @classmethod
    def get_override( cls, name ):
        """
        Return the payload injected under ``name`` (consuming it when it was
        injected one_time), or None if there is none. Checks the cache first,
        then the file store. Returns None outside DEBUG.
        """
        if not settings.DEBUG:
            return None

        cache_key = f'{cls.CACHE_PREFIX}{name}'
        entry = cache.get( cache_key )
        if entry is not None:
            if entry.get('one_time'):
                cache.delete( cache_key )
                cls._cache_index_remove( name )
            return entry.get('data')

        file_path = cls._get_file_path( name )
        if os.path.exists( file_path ):
            try:
                with open( file_path ) as f:
                    entry = json.load( f )
            except ( IOError, ValueError ) as e:
                logger.error( 'DevInjection: failed to read override %r: %s', name, e )
                return None
            if entry.get('one_time'):
                try:
                    os.remove( file_path )
                except OSError:
                    pass
            return entry.get('data')

        return None

    @classmethod
    def inject_override_if_available( cls, name, data_dict, key ):
        """
        Convenience for the single-line pattern at an injection point: if an
        override for ``name`` is available, set ``data_dict[key]`` to it.
        """
        payload = cls.get_override( name )
        if payload is not None:
            data_dict[key] = payload
            logger.info( 'DevInjection: applied override %r', name )

    # -- management --------------------------------------------------------

    @classmethod
    def list_active_overrides( cls ):
        """Return ``{name: 'cache'|'file'}`` for all currently active overrides."""
        if not settings.DEBUG:
            return {}
        active = {}
        for name in cls._cache_index():
            if cache.get( f'{cls.CACHE_PREFIX}{name}' ) is not None:
                active[name] = 'cache'
        if os.path.exists( cls.DATA_DIR ):
            for filename in os.listdir( cls.DATA_DIR ):
                if filename.endswith('.json'):
                    active[ filename[ :-len('.json') ] ] = 'file'
        return active

    @classmethod
    def clear_all_overrides( cls ):
        """Remove all cache- and file-based overrides. Returns True in DEBUG."""
        if not settings.DEBUG:
            return False
        for name in cls._cache_index():
            cache.delete( f'{cls.CACHE_PREFIX}{name}' )
        cache.delete( cls.CACHE_INDEX_KEY )
        if os.path.exists( cls.DATA_DIR ):
            for filename in os.listdir( cls.DATA_DIR ):
                if filename.endswith('.json'):
                    try:
                        os.remove( os.path.join( cls.DATA_DIR, filename ) )
                    except OSError as e:
                        logger.error( 'DevInjection: error removing %s: %s', filename, e )
        logger.info( 'DevInjection: cleared all overrides' )
        return True
