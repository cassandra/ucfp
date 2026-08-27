"""Env-driven Redis logical-database selection. One host Redis can be shared by
several apps built from this same image; because they bake an identical cache
KEY_PREFIX, only a distinct logical DB index keeps their keyspaces apart. These
tests pin the mapping from the `UCFP_REDIS_DB_INDEX` shell variable through
`get()` into the field settings/base.py reads when it builds the cache LOCATION,
and the single-app default.
"""
from unittest import mock

from django.test import SimpleTestCase

from ucfp.environment.server import EnvironmentSettings
from ucfp.settings import base as base_settings


# The environment get() requires, over which each test overlays a Redis choice.
_BASE_ENV = {
    'DJANGO_SETTINGS_MODULE'   : 'ucfp.settings.ci',
    'DJANGO_SECRET_KEY'        : 'test-secret-key',
    'DJANGO_SUPERUSER_EMAIL'   : 'admin@example.com',
    'DJANGO_SUPERUSER_PASSWORD': 'test-password',
    'UCFP_MEDIA_PATH'          : '/data/media',
    'UCFP_DB_PATH'             : '/data/database',
}


class RedisDatabaseIndexTests( SimpleTestCase ):

    def test_redis_db_index_resolves( self ):
        environ = dict( _BASE_ENV, UCFP_REDIS_DB_INDEX = '3' )
        with mock.patch.dict( 'os.environ', environ, clear = True ):
            env = EnvironmentSettings.get()
        self.assertEqual( env.REDIS_DB_INDEX, 3 )

    def test_redis_db_index_defaults_to_zero( self ):
        # Unset -- the single-app case -- must be DB 0, preserving prior behavior.
        with mock.patch.dict( 'os.environ', dict( _BASE_ENV ), clear = True ):
            env = EnvironmentSettings.get()
        self.assertEqual( env.REDIS_DB_INDEX, 0 )


class RedisCacheLocationTests( SimpleTestCase ):
    """The cache URL settings/base.py builds must carry the logical DB index as a
    path suffix -- without it, two co-hosted apps silently share DB 0 and the
    isolation is a no-op. Read from the base settings module directly, since the
    test settings override CACHES to an in-memory backend with no redis LOCATION."""

    def test_cache_location_carries_db_index( self ):
        location = base_settings.CACHES[ 'default' ][ 'LOCATION' ][ 0 ]
        self.assertRegex( location, r'^redis://[^/]+:\d+/\d+$' )
        self.assertTrue( location.endswith( f'/{base_settings.REDIS_DB_INDEX}' ) )
