from dataclasses import dataclass, field
import os
import re
import sys
from typing import Tuple
import urllib.parse

from django.core.exceptions import ImproperlyConfigured


# ---------------------------------------------------------------------------
# Project token
#
# This is the ONE acronym-derived value in this module. Shell environment
# variables are namespaced with this prefix (e.g. "UCFP_DB_PATH") because the
# shell environment is shared across projects and needs namespacing. The
# internal field names on EnvironmentSettings are deliberately prefix-free so
# they stay constant from project to project; only this constant (and the
# package directory name) changes when adapting the template to a new project.
# ---------------------------------------------------------------------------
ENV_PREFIX = 'UCFP_'

# The human-readable long form of the project name. Like ENV_PREFIX this is a
# per-project token, kept here next to it as the single place to set it. Used
# for display purposes (e.g. SITE_NAME) and referenced elsewhere in the code.
PROJECT_NAME = 'Landfall'

# The version file lives at the project root and is the single source of truth
# for the running version. The name is intentionally generic (no acronym) so
# it never needs renaming between projects.
VERSION_FILENAME = 'VERSION'


@dataclass( frozen = True )
class _EnvVarSpec:
    """One row of the environment-variable mapping: which shell variable feeds
    which internal field, how to coerce the raw value, and its default.

    A default of None marks the variable as required: its absence raises
    ImproperlyConfigured.
    """
    field    : str            # EnvironmentSettings attribute to populate
    env_name : str            # Shell environment variable name to read
    kind     : type = str     # str, int, or bool -- how to coerce the raw value
    default  : object = None  # None => required


# The single mapping from shell environment variable -> internal field. This
# is the one place to add, remove, or rename a straightforward variable when
# adapting the template; only ENV_PREFIX above needs to change per project.
#
# Variables that need cross-field logic (the version file, the TLS/SSL
# interaction, the email subject spacing, host/CORS/CSP assembly) are handled
# explicitly in EnvironmentSettings.get() rather than in this table.
_ENV_SPEC = (

    # Core Django settings -- standard names, intentionally NOT project-prefixed.
    _EnvVarSpec( 'DJANGO_SETTINGS_MODULE'   , 'DJANGO_SETTINGS_MODULE' ),
    _EnvVarSpec( 'DJANGO_SERVER_PORT'       , 'DJANGO_SERVER_PORT', int, 8000 ),
    _EnvVarSpec( 'SECRET_KEY'               , 'DJANGO_SECRET_KEY' ),
    _EnvVarSpec( 'DJANGO_SUPERUSER_EMAIL'   , 'DJANGO_SUPERUSER_EMAIL' ),
    _EnvVarSpec( 'DJANGO_SUPERUSER_PASSWORD', 'DJANGO_SUPERUSER_PASSWORD' ),

    # Database selection: SQLite (file-based) or MySQL (server-based). Both are
    # optional here; validate_database_config() (from get()) requires at least one
    # (MySQL wins if both are set). This env-driven switch is what lets one image
    # serve both the self-host (SQLite) and cloud (MySQL) lanes. SQLite path:
    _EnvVarSpec( 'DATABASES_NAME_PATH'      , ENV_PREFIX + 'DB_PATH', str, '' ),
    # MySQL connection (all five required together):
    _EnvVarSpec( 'DATABASE_HOST'            , ENV_PREFIX + 'DB_HOST', str, '' ),
    _EnvVarSpec( 'DATABASE_PORT'            , ENV_PREFIX + 'DB_PORT', str, '' ),
    _EnvVarSpec( 'DATABASE_NAME'            , ENV_PREFIX + 'DB_NAME', str, '' ),
    _EnvVarSpec( 'DATABASE_USER'            , ENV_PREFIX + 'DB_USER', str, '' ),
    _EnvVarSpec( 'DATABASE_PASSWORD'        , ENV_PREFIX + 'DB_PASSWORD', str, '' ),

    # Media path.
    _EnvVarSpec( 'MEDIA_ROOT'               , ENV_PREFIX + 'MEDIA_PATH' ),

    # Redis.
    _EnvVarSpec( 'REDIS_HOST'               , ENV_PREFIX + 'REDIS_HOST', str, 'localhost' ),
    _EnvVarSpec( 'REDIS_PORT'               , ENV_PREFIX + 'REDIS_PORT', int, 6379 ),

    # Email.
    _EnvVarSpec( 'EMAIL_SUBJECT_PREFIX'     , ENV_PREFIX + 'EMAIL_SUBJECT_PREFIX', str, '' ),
    _EnvVarSpec( 'DEFAULT_FROM_EMAIL'       , ENV_PREFIX + 'DEFAULT_FROM_EMAIL', str, '' ),
    _EnvVarSpec( 'SERVER_EMAIL'             , ENV_PREFIX + 'SERVER_EMAIL', str, '' ),
    _EnvVarSpec( 'EMAIL_HOST'               , ENV_PREFIX + 'EMAIL_HOST', str, '' ),
    _EnvVarSpec( 'EMAIL_PORT'               , ENV_PREFIX + 'EMAIL_PORT', int, 587 ),
    _EnvVarSpec( 'EMAIL_HOST_USER'          , ENV_PREFIX + 'EMAIL_HOST_USER', str, '' ),
    _EnvVarSpec( 'EMAIL_HOST_PASSWORD'      , ENV_PREFIX + 'EMAIL_HOST_PASSWORD', str, '' ),
    _EnvVarSpec( 'EMAIL_USE_TLS'            , ENV_PREFIX + 'EMAIL_USE_TLS', bool, False ),
    _EnvVarSpec( 'EMAIL_USE_SSL'            , ENV_PREFIX + 'EMAIL_USE_SSL', bool, False ),

    # Application-specific.
    _EnvVarSpec( 'SUPPRESS_AUTHENTICATION'  , ENV_PREFIX + 'SUPPRESS_AUTHENTICATION', bool, False ),

    # Consumed by the container entrypoint/supervisord (not by Django) to decide
    # whether to run redis inside the image (self-host lane) or use host redis
    # (cloud lane). Declared here so it is part of the one canonical env surface.
    _EnvVarSpec( 'BUNDLED_REDIS'            , ENV_PREFIX + 'BUNDLED_REDIS', bool, False ),
)


def all_env_var_names():
    """
    Every shell environment variable the app reads: the _ENV_SPEC table plus the
    extras parsed directly in EnvironmentSettings.get() (the list-valued EXTRA_*
    and the secret-URL UUID). This is the single source of truth that
    deploy/env-generate.py's output is checked against by deploy/env-drift-check.sh.
    """
    names = [ spec.env_name for spec in _ENV_SPEC ]
    names += [ ENV_PREFIX + 'EXTRA_HOST_URLS', ENV_PREFIX + 'EXTRA_CSP_URLS',
               ENV_PREFIX + 'SECRET_URL_PREFIX_UUID', ENV_PREFIX + 'FIELD_ENCRYPTION_KEY' ]
    return names


@dataclass
class EnvironmentSettings:
    """
    Encapsulates the parsing of the environment variables that are needed.

    The mapping from shell environment variable names to these internal
    fields lives in the _ENV_SPEC table above -- that is the single place to
    add, remove, or rename a straightforward variable. These field names are
    intentionally free of the project acronym so they stay constant across
    projects; only ENV_PREFIX (and the per-project deployment env files)
    change when adapting the template.
    """

    # If the default value is "None" then the variable is required and its
    # absence will raise an ImproperlyConfigured error.  Optional
    # arguments should have a non-None value (empty string, zero, etc.)
    #
    DJANGO_SETTINGS_MODULE     : str           = None
    DJANGO_SERVER_PORT         : int           = 8000
    VERSION                    : str           = 'unknown'
    SECRET_KEY                 : str           = None
    DJANGO_SUPERUSER_EMAIL     : str           = None
    DJANGO_SUPERUSER_PASSWORD  : str           = None
    SITE_ID                    : str           = 1
    SITE_DOMAIN                : str           = 'localhost'
    SITE_NAME                  : str           = PROJECT_NAME
    ALLOWED_HOSTS              : Tuple[ str ]  = field( default_factory = tuple )
    CORS_ALLOWED_ORIGINS       : Tuple[ str ]  = field( default_factory = tuple )
    EXTRA_CSP_URLS             : Tuple[ str ]  = field( default_factory = tuple )
    DATABASES_NAME_PATH        : str           = ''
    DATABASE_HOST              : str           = ''
    DATABASE_PORT              : str           = ''
    DATABASE_NAME              : str           = ''
    DATABASE_USER              : str           = ''
    DATABASE_PASSWORD          : str           = ''
    MEDIA_ROOT                 : str           = None
    REDIS_HOST                 : str           = 'localhost'
    REDIS_PORT                 : int           = 6379
    SUPPRESS_AUTHENTICATION    : bool          = False
    BUNDLED_REDIS              : bool          = False
    FIELD_ENCRYPTION_KEYS      : Tuple[ str ]  = field( default_factory = tuple )
    SECRET_URL_PREFIX          : str           = ''
    EMAIL_SUBJECT_PREFIX       : str           = ''
    DEFAULT_FROM_EMAIL         : str           = ''
    SERVER_EMAIL               : str           = ''
    EMAIL_HOST                 : str           = ''
    EMAIL_PORT                 : int           = 587
    EMAIL_HOST_USER            : str           = ''
    EMAIL_HOST_PASSWORD        : str           = ''
    EMAIL_USE_TLS              : bool          = False
    EMAIL_USE_SSL              : bool          = False

    @property
    def environment_name(self) -> str:
        """
        Extract environment name from DJANGO_SETTINGS_MODULE.
        """
        if not self.DJANGO_SETTINGS_MODULE:
            return 'unknown'

        parts = self.DJANGO_SETTINGS_MODULE.split('.')
        if len(parts) > 1:
            return parts[-1]
        return 'unknown'

    def _mysql_field_values(self) -> Tuple[ str, ... ]:
        """The five MySQL connection values, whitespace-stripped so a blank or
        whitespace-only variable counts as unset (an all-whitespace host must not
        read as a configured backend)."""
        fields = ( self.DATABASE_HOST, self.DATABASE_PORT, self.DATABASE_NAME,
                   self.DATABASE_USER, self.DATABASE_PASSWORD, )
        return tuple( ( value or '' ).strip() for value in fields )

    @property
    def uses_mysql(self) -> bool:
        """Whether the MySQL backend is selected: true when the full MySQL
        connection set is configured, false otherwise (SQLite). MySQL wins when
        both backends are configured -- see validate_database_config()."""
        return all( self._mysql_field_values() )

    def validate_database_config(self) -> None:
        """Require a usable database backend, chosen from the environment so one
        image serves every deployment. MySQL is used when its full connection set
        (DB_HOST/PORT/NAME/USER/PASSWORD) is present; otherwise SQLite is used when
        a file path (DB_PATH) is given.

        When both are configured MySQL takes precedence. This is what lets a
        self-hoster switch to an external MySQL by simply adding the MySQL
        variables, without also having to clear the default SQLite path. A partial
        MySQL set (some but not all variables), or no backend at all, is a
        misconfiguration surfaced at startup.
        """
        mysql_values      = self._mysql_field_values()
        has_mysql         = all( mysql_values )
        has_partial_mysql = any( mysql_values ) and not has_mysql
        has_sqlite        = bool( self.DATABASES_NAME_PATH.strip() )

        if has_partial_mysql:
            raise ImproperlyConfigured(
                f"Incomplete MySQL configuration: set all of {ENV_PREFIX}DB_HOST, "
                f"{ENV_PREFIX}DB_PORT, {ENV_PREFIX}DB_NAME, {ENV_PREFIX}DB_USER and "
                f"{ENV_PREFIX}DB_PASSWORD together, or none of them." )
        if not has_mysql and not has_sqlite:
            raise ImproperlyConfigured(
                f"No database configured. Provide either {ENV_PREFIX}DB_PATH (SQLite) "
                f"or the {ENV_PREFIX}DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD set "
                f"(MySQL)." )
        return

    @classmethod
    def get( cls ) -> 'EnvironmentSettings':
        env_settings = EnvironmentSettings()

        ###########
        # Straightforward scalar variables, driven entirely by the mapping
        # table.  DJANGO_SETTINGS_MODULE is parsed by Django before this module
        # ever executes; we include it so there is one place to see every env
        # var required, but the application code does not use it directly.
        #
        for spec in _ENV_SPEC:
            raw_value = cls.get_env_variable( spec.env_name, spec.default )
            setattr( env_settings, spec.field,
                     cls._coerce( spec.kind, raw_value, spec.default ) )

        ###########
        # Variables that need more than a simple read.

        # Version: single source of truth is the VERSION file at project root.
        env_settings.VERSION = cls._read_version()

        # The email subject prefix carries a trailing space separator.
        env_settings.EMAIL_SUBJECT_PREFIX = "%s " % env_settings.EMAIL_SUBJECT_PREFIX

        # TLS and SSL are mutually exclusive; TLS wins when both are requested.
        if env_settings.EMAIL_USE_TLS:
            env_settings.EMAIL_USE_SSL = False

        # Public-facing deployments hide the admin-only entry points (the Django
        # admin and the env inspector) behind an unguessable URL prefix -- see
        # ucfp/urls.py. The env var holds a bare token (a UUID); we append the
        # slash so the routes compose cleanly. Blank => routes stay at /admin/.
        secret_url_prefix_uuid = cls.get_env_variable( ENV_PREFIX + 'SECRET_URL_PREFIX_UUID', '' )
        if secret_url_prefix_uuid:
            env_settings.SECRET_URL_PREFIX = f'{secret_url_prefix_uuid}/'

        # Field-encryption keys are a comma-separated list so keys can rotate: the
        # first encrypts, all decrypt. Parsed into a tuple here; empty when unset,
        # which the encrypted fields treat as "not configured".
        raw_field_encryption_keys = cls.get_env_variable( ENV_PREFIX + 'FIELD_ENCRYPTION_KEY', '' )
        env_settings.FIELD_ENCRYPTION_KEYS = tuple(
            key.strip() for key in raw_field_encryption_keys.split( ',' ) if key.strip() )

        ###########
        # Extras to satisfy security requirements:
        #   - Django strict host checking
        #   - web browser CORS/CSP issues

        allowed_host_list = [
            '127.0.0.1',
            'localhost',
        ]
        cors_allowed_origins_list = [
            f'http://127.0.0.1:{env_settings.DJANGO_SERVER_PORT}',
            f'http://localhost:{env_settings.DJANGO_SERVER_PORT}',
        ]

        extra_host_urls_str = cls.get_env_variable( ENV_PREFIX + 'EXTRA_HOST_URLS', '' )
        if extra_host_urls_str:
            host_url_tuple_list = cls.parse_url_list_str(
                extra_host_urls_str, source_var = ENV_PREFIX + 'EXTRA_HOST_URLS' )

            # Assume first extra host is the SITE_DOMAIN, but this does not
            # matter until the Django "sites" feature needs to be used (if
            # ever).
            #
            if host_url_tuple_list:
                env_settings.SITE_DOMAIN = host_url_tuple_list[0][0]

            for host, url in host_url_tuple_list:
                allowed_host_list.append( host )
                cors_allowed_origins_list.append( url )
                continue

        extra_csp_urls_str = cls.get_env_variable( ENV_PREFIX + 'EXTRA_CSP_URLS', '' )
        if extra_csp_urls_str:
            host_url_tuple_list = cls.parse_url_list_str(
                extra_csp_urls_str, source_var = ENV_PREFIX + 'EXTRA_CSP_URLS' )
            for host, url in host_url_tuple_list:
                cors_allowed_origins_list.append( url )
                continue

        if allowed_host_list:
            env_settings.ALLOWED_HOSTS += tuple( allowed_host_list )

        # For now, forego any fine-grained control of the allowed urls for CORS and CSP
        if cors_allowed_origins_list:
            env_settings.CORS_ALLOWED_ORIGINS += tuple( cors_allowed_origins_list )
            env_settings.EXTRA_CSP_URLS += tuple( cors_allowed_origins_list )

        env_settings.validate_database_config()

        return env_settings

    @classmethod
    def _coerce( cls, kind, raw_value, default ):
        """Coerce a raw env value (string, or the spec default) to the field
        type.  A malformed int falls back to the default rather than crashing,
        matching the original lenient parsing."""
        if kind is bool:
            return cls.to_bool( raw_value )
        if kind is int:
            try:
                return int( raw_value )
            except ( TypeError, ValueError ):
                return default
        return raw_value

    @classmethod
    def _read_version( cls ) -> str:
        version_file_path = os.path.join(
            os.path.dirname( __file__ ), '..', '..', '..', VERSION_FILENAME )
        try:
            with open( version_file_path, 'r' ) as f:
                return f.read().strip()
        except ( FileNotFoundError, IOError ) as e:
            raise ImproperlyConfigured( f"Cannot read version file {version_file_path}: {e}" )

    @classmethod
    def get_env_variable( cls, var_name, default = None ) -> str:
        try:
            return os.environ[var_name]
        except KeyError:
            if default is not None:
                return default
            error_msg = "Set the %s environment variable" % var_name
            raise ImproperlyConfigured(error_msg)

    @classmethod
    def to_bool( cls, value: object ) -> bool:
        if isinstance( value, bool ):
            return value
        if isinstance( value, str ):
            truthy_values = {'true', '1', 'on', 'yes', 'y', 't', 'enabled'}
            return value.strip().lower() in truthy_values
        return bool( value )

    @classmethod
    def parse_url_list_str( cls, a_string : str, source_var : str = ENV_PREFIX + 'EXTRA_HOST_URLS' ):
        url_str_list = re.split( r'[\s\;\,]+', a_string )
        host_url_tuple_list = list()
        for url_str in url_str_list:
            if not url_str:
                continue
            try:
                parsed_url = cls.parse_url( url_str )
                scheme = parsed_url.scheme
                host = parsed_url.hostname
                port = parsed_url.port
                if port:
                    normalized_url_str = f'{scheme}://{host}:{port}'
                else:
                    normalized_url_str = f'{scheme}://{host}'
                host_url_tuple_list.append( ( host, normalized_url_str ) )

            except ( TypeError, ValueError ):
                # Loud, actionable feedback rather than a silent drop. Without
                # this, a bare hostname (exactly what Django's DisallowedHost
                # error tells users to add) is discarded with no signal. This
                # runs during settings construction, before Django logging is
                # configured, so write to stderr -- it surfaces in `docker logs`
                # / compose output at startup, where the user is already looking.
                # The example is fixed (not built from the bad input, which
                # could produce a nonsense suggestion).
                print(
                    f"WARNING: {source_var} value '{url_str}' was ignored -- entries "
                    f"must be full URLs including the scheme and the port you browse "
                    f"to, e.g. 'http://myhost:9666'. See Installation.md.",
                    file = sys.stderr,
                )
            continue
        return host_url_tuple_list

    @classmethod
    def parse_url( cls, url_str : str ) -> urllib.parse.ParseResult:
        if not url_str:
            raise ValueError()
        try:
            parsed_url = urllib.parse.urlparse( url_str )
            if not ( parsed_url.scheme and parsed_url.netloc ):
                raise ValueError()
            return parsed_url
        except TypeError:
            pass
        raise ValueError()
