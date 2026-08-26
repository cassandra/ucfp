"""Env-driven database backend selection. One Docker image serves both deployment
lanes, so the backend (SQLite for self-host, MySQL for the cloud droplet) is chosen
from the environment. These tests pin the discriminator (`uses_mysql`), the
"exactly one backend, fully specified" contract enforced by
`validate_database_config()`, and the end-to-end mapping from `UCFP_DB_*` shell
variables through `get()` into Django's DATABASES-facing fields.
"""
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from ucfp.environment.server import EnvironmentSettings


# The non-database environment variables that get() requires; the tests overlay a
# database choice on top of these.
_BASE_ENV = {
    'DJANGO_SETTINGS_MODULE'   : 'ucfp.settings.ci',
    'DJANGO_SECRET_KEY'        : 'test-secret-key',
    'DJANGO_SUPERUSER_EMAIL'   : 'admin@example.com',
    'DJANGO_SUPERUSER_PASSWORD': 'test-password',
    'UCFP_MEDIA_PATH'          : '/data/media',
}

_MYSQL_ENV = {
    'UCFP_DB_HOST'    : 'db.internal',
    'UCFP_DB_PORT'    : '3306',
    'UCFP_DB_NAME'    : 'ucfp_prod',
    'UCFP_DB_USER'    : 'ucfp',
    'UCFP_DB_PASSWORD': 'secret',
}


def _mysql_settings( **overrides ) -> EnvironmentSettings:
    values = {
        'DATABASE_HOST'    : 'db.internal',
        'DATABASE_PORT'    : '3306',
        'DATABASE_NAME'    : 'ucfp_prod',
        'DATABASE_USER'    : 'ucfp',
        'DATABASE_PASSWORD': 'secret',
    }
    values.update( overrides )
    return EnvironmentSettings( **values )


class DatabaseConfigValidationTests( SimpleTestCase ):
    """validate_database_config() on directly-constructed settings -- the pure
    decision logic, isolated from environment reading."""

    def test_sqlite_only_is_valid( self ):
        settings = EnvironmentSettings( DATABASES_NAME_PATH = '/data/database' )
        settings.validate_database_config()          # does not raise
        self.assertFalse( settings.uses_mysql )

    def test_complete_mysql_is_valid( self ):
        settings = _mysql_settings()
        settings.validate_database_config()          # does not raise
        self.assertTrue( settings.uses_mysql )

    def test_partial_mysql_is_rejected( self ):
        settings = _mysql_settings( DATABASE_PASSWORD = '' )
        with self.assertRaises( ImproperlyConfigured ):
            settings.validate_database_config()

    def test_partial_mysql_missing_host_is_rejected( self ):
        # The most likely misconfiguration: the other four set but the host
        # forgotten. Must still be rejected, not silently fall through to SQLite.
        settings = _mysql_settings( DATABASE_HOST = '' )
        self.assertFalse( settings.uses_mysql )
        with self.assertRaises( ImproperlyConfigured ):
            settings.validate_database_config()

    def test_whitespace_only_mysql_counts_as_unset( self ):
        # A whitespace-only value must not read as a configured backend.
        settings = _mysql_settings(
            DATABASE_HOST = '   ', DATABASE_PORT = '', DATABASE_NAME = '',
            DATABASE_USER = '', DATABASE_PASSWORD = '',
            DATABASES_NAME_PATH = '/data/database' )
        settings.validate_database_config()          # does not raise (SQLite)
        self.assertFalse( settings.uses_mysql )

    def test_mysql_takes_precedence_when_both_configured( self ):
        # A self-hoster who adds MySQL variables gets MySQL without having to also
        # clear the default SQLite path.
        settings = _mysql_settings( DATABASES_NAME_PATH = '/data/database' )
        settings.validate_database_config()          # does not raise
        self.assertTrue( settings.uses_mysql )

    def test_no_backend_configured_is_rejected( self ):
        settings = EnvironmentSettings()
        with self.assertRaises( ImproperlyConfigured ):
            settings.validate_database_config()


class DatabaseEnvironmentMappingTests( SimpleTestCase ):
    """End-to-end: shell UCFP_DB_* variables resolved by get() into the fields
    settings/base.py reads when it builds DATABASES."""

    def test_sqlite_path_selects_sqlite( self ):
        environ = dict( _BASE_ENV, UCFP_DB_PATH = '/data/database' )
        with mock.patch.dict( 'os.environ', environ, clear = True ):
            settings = EnvironmentSettings.get()
        self.assertFalse( settings.uses_mysql )
        self.assertEqual( settings.DATABASES_NAME_PATH, '/data/database' )

    def test_mysql_variables_select_mysql( self ):
        environ = dict( _BASE_ENV, **_MYSQL_ENV )
        with mock.patch.dict( 'os.environ', environ, clear = True ):
            settings = EnvironmentSettings.get()
        self.assertTrue( settings.uses_mysql )
        self.assertEqual( settings.DATABASE_HOST    , 'db.internal' )
        self.assertEqual( settings.DATABASE_PORT    , '3306' )
        self.assertEqual( settings.DATABASE_NAME    , 'ucfp_prod' )
        self.assertEqual( settings.DATABASE_USER    , 'ucfp' )
        self.assertEqual( settings.DATABASE_PASSWORD, 'secret' )

    def test_missing_database_configuration_raises( self ):
        with mock.patch.dict( 'os.environ', dict( _BASE_ENV ), clear = True ):
            with self.assertRaises( ImproperlyConfigured ):
                EnvironmentSettings.get()

    def test_mysql_takes_precedence_over_sqlite_path( self ):
        environ = dict( _BASE_ENV, UCFP_DB_PATH = '/data/database', **_MYSQL_ENV )
        with mock.patch.dict( 'os.environ', environ, clear = True ):
            settings = EnvironmentSettings.get()
        self.assertTrue( settings.uses_mysql )

    def test_empty_db_host_falls_back_to_sqlite( self ):
        # An explicitly empty UCFP_DB_HOST (as a compose .env file commonly emits)
        # is equivalent to unset -- SQLite is used.
        environ = dict( _BASE_ENV, UCFP_DB_PATH = '/data/database', UCFP_DB_HOST = '' )
        with mock.patch.dict( 'os.environ', environ, clear = True ):
            settings = EnvironmentSettings.get()
        self.assertFalse( settings.uses_mysql )

    def test_bundled_redis_flag_resolves( self ):
        base_sqlite = dict( _BASE_ENV, UCFP_DB_PATH = '/data/database' )
        with mock.patch.dict( 'os.environ',
                              dict( base_sqlite, UCFP_BUNDLED_REDIS = 'true' ), clear = True ):
            self.assertTrue( EnvironmentSettings.get().BUNDLED_REDIS )
        with mock.patch.dict( 'os.environ', base_sqlite, clear = True ):
            self.assertFalse( EnvironmentSettings.get().BUNDLED_REDIS )
