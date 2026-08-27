from pathlib import Path
import os
import sys

from ucfp.environment.server import EnvironmentSettings

ENV = EnvironmentSettings.get()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = ENV.SECRET_KEY

DJANGO_SUPERUSER_EMAIL = ENV.DJANGO_SUPERUSER_EMAIL
DJANGO_SUPERUSER_PASSWORD = ENV.DJANGO_SUPERUSER_PASSWORD

SITE_ID = ENV.SITE_ID
SITE_DOMAIN = ENV.SITE_DOMAIN
SITE_NAME = ENV.SITE_NAME

ALLOWED_HOSTS = ENV.ALLOWED_HOSTS

CORS_ALLOWED_ORIGINS = ENV.CORS_ALLOWED_ORIGINS

# django-csp 4.x dict-based config. Directive keys are kebab-case
# without the ``CSP_`` prefix (see django-csp migration guide). Each
# value concatenates with ENV.EXTRA_CSP_URLS so deployments can extend
# the allow-lists without editing source.
CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': (
            "'self'",
            'data:',
        ) + ENV.EXTRA_CSP_URLS,
        'connect-src': (
            "'self'",
        ) + ENV.EXTRA_CSP_URLS,
        'frame-src': (
            "'self'",
        ) + ENV.EXTRA_CSP_URLS,
        'script-src': (
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",
        ) + ENV.EXTRA_CSP_URLS,
        'style-src': (
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",
        ) + ENV.EXTRA_CSP_URLS,
        'media-src': (
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",
            'data:',
        ) + ENV.EXTRA_CSP_URLS,
        'img-src': (
            "'self'",
            'data:',
        ) + ENV.EXTRA_CSP_URLS,
        'child-src': (
            "'self'",
        ) + ENV.EXTRA_CSP_URLS,
        'font-src': (
            "'self'",
            'data:',
        ) + ENV.EXTRA_CSP_URLS,
        'worker-src': (
            "'self'",
        ) + ENV.EXTRA_CSP_URLS,
    },
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.forms',
    'pipeline',
    'django.contrib.humanize',
    'constance',
    'custom',
    'common',
    'notify',
    'user',
    'organization',
    'ucfp.accounts',
    'ucfp.period',
    'ucfp.forecast',
    'ucfp.jurisdiction',
    'ucfp.parameter_sets',
    'ucfp.inputs',
    'ucfp.planning',
    'ucfp.onboarding',
    'ucfp.environment',
]

MIDDLEWARE = [
    'csp.middleware.CSPMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Attaches request.session_state (typed view of the session) -- right after
    # SessionMiddleware, which it reads from.
    'ucfp.middleware.SessionStateMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Logs the self-hosted singleton Guest in under SUPPRESS_AUTHENTICATION, so the request
    # carries a real user before the sign-in gate (and every downstream view) runs.
    'user.middleware.SelfHostedIdentityMiddleware',
    'user.middleware.AuthenticationMiddleware',
    # Attaches request.show_privacy_banner -- after the auth middleware, whose
    # request.user it reads (and after SessionStateMiddleware above).
    'ucfp.middleware.PrivacyBannerMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Stamp `Cache-Control: no-store` on dynamic HTML/JSON. Outer of
    # ExceptionMiddleware so it also covers the error responses it produces.
    'ucfp.middleware.NoStoreMiddleware',
    # Innermost: wraps the view so it can turn raised exceptions / bare error
    # responses into the project's rich error responses (request.user is set
    # by the auth middleware above before this renders an error page).
    'ucfp.middleware.ExceptionMiddleware',
]

ROOT_URLCONF = 'ucfp.urls'

# Use the template-based form renderer so form / field / widget rendering resolves
# through the project template loaders. This lets templates/django/forms/field.html
# shadow Django's default field markup app-wide (a single place to style every
# field). Requires 'django.forms' in INSTALLED_APPS so its widget templates stay
# resolvable via the app-directories loader.
FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [ os.path.join(BASE_DIR, "templates") ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'ucfp.environment.context_processors.client_config',
                'ucfp.environment.context_processors.shared_constants',
                'organization.context_processors.current_currency',
                'organization.context_processors.can_edit_organization',
                'ucfp.onboarding.context_processors.add_my_data_offer',
            ],
        },
    },
]

WSGI_APPLICATION = 'ucfp.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
#
# The backend is chosen from the environment so that one Docker image can serve
# both deployment lanes: SQLite for the zero-dependency self-hosted install, and
# MySQL for the cloud (droplet) install. The environment layer
# (ucfp.environment.server) validates that a usable backend is configured (MySQL
# wins if both are); here we merely materialize the choice. See
# docs/dev/project/droplet-setup.md.
if ENV.uses_mysql:
    DATABASES = {
        'default': {
            'ENGINE'  : 'django.db.backends.mysql',
            'HOST'    : ENV.DATABASE_HOST,
            'PORT'    : ENV.DATABASE_PORT,
            'NAME'    : ENV.DATABASE_NAME,
            'USER'    : ENV.DATABASE_USER,
            'PASSWORD': ENV.DATABASE_PASSWORD,
            # Pin the client connection charset so 4-byte characters round-trip
            # regardless of the server's negotiated default (the DB is created
            # utf8mb4 -- see docs/dev/project/droplet-setup.md).
            'OPTIONS' : { 'charset': 'utf8mb4' },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME'  : os.path.join( ENV.DATABASES_NAME_PATH, 'ucfp.sqlite3' ),
        }
    }


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Passwordless sign-in: how long an emailed one-time code (and the magic link in
# the same email) stays valid. Kept short to limit code-guessing on the sign-in
# form -- long enough to absorb email-delivery lag, not the multi-day window
# Django's PASSWORD_RESET_TIMEOUT defaults to. The emailed link is validated by
# PasswordResetTokenGenerator, which reads PASSWORD_RESET_TIMEOUT internally, so
# we point that at the same value to keep the code and the link expiring together.
SIGNIN_CODE_TIMEOUT_SECS = 15 * 60
PASSWORD_RESET_TIMEOUT   = SIGNIN_CODE_TIMEOUT_SECS

# True when invoked as ``manage.py test`` (WSGI / gunicorn / runserver /
# migrate / shell do not match, so production processes are unaffected).
# Drives test-only behavior: the fast password hasher below, plus the
# synchronous-in-test guards in email_utils, metrics, and
# DelayedSignalProcessor.
UNIT_TESTING = ( sys.argv[1:2] == ['test'] )

# Default PBKDF2 hashing is hundreds of ms per call by design; for tests
# (where many setUps create a user) it dominates wall time. Swap to a
# fast hasher under test.
if UNIT_TESTING:
    PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.MD5PasswordHasher',
    ]

# Sign-in abuse prevention (rate limits, verify cooldown, alerting). On for real
# deployments; off under the test suite (so unrelated tests are not throttled --
# the dedicated abuse tests re-enable it via @override_settings) and off in local
# development (see settings/development.py). A self-host that wants it off can
# override this in its own settings module.
ABUSE_PREVENTION_ENABLED = not UNIT_TESTING


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'

STATICFILES_DIRS = (
    os.path.join(BASE_DIR, "static"),
)

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_ROOT = ENV.MEDIA_ROOT
MEDIA_URL = '/media/'

PIPELINE = {
    'DISABLE_WRAPPER': True,  # Important since some scripts assume global scope

    'CSS_COMPRESSOR': None,  # Removed django-pipeline-csscompressor (unmaintained since 2016)
    'JS_COMPRESSOR': None,
    
    'STYLESHEETS': {
        'css_head': {
            'source_filenames': (
                'bootstrap/css/bootstrap.css',
                'css/bootstrap-datepicker.standalone.min.css',
                'css/main.css',
                'css/books_table.css',
            ),
            'output_filename': 'css/css_head.css',
        },
    },
    'JAVASCRIPT': {
        'js_before_content': {
            'source_filenames': (
                'js/jquery-3.7.0.min.js',
                'js/cookie.js',
                'js/antinode.js',
                'js/autosize.min.js',
                'js/bootstrap-datepicker.min.js',
                'js/main.js',
                'js/inputs.js',
            ),
            'output_filename': 'js/js_before_content.js',
        },
        'js_after_content': {
            'source_filenames': (
                'js/popper.min.js',
                'bootstrap/js/bootstrap.js',
            ),
            'output_filename': 'js/js_after_content.js',
        },
    }
}

SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365  # in seconds
AUTO_LOGOUT = 60 * 24 * 365 * 100  # in minutes

CONSTANCE_BACKEND = 'constance.backends.database.DatabaseBackend'
CONSTANCE_DATABASE_CACHE_BACKEND = 'default'
CONSTANCE_DATABASE_PREFIX = 'constance:ucfp:'

CONSTANCE_CONFIG = {
    'DOWN_FOR_MAINTENANCE': ( False, 'Should we force the down for maintenance page to show?' ),
}

REDIS_HOST     = ENV.REDIS_HOST
REDIS_PORT     = ENV.REDIS_PORT
REDIS_DB_INDEX = ENV.REDIS_DB_INDEX

CACHES = {
    'default': {
        # 'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': [
            f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_INDEX}',
        ],
        "KEY_PREFIX": 'main:',
    }
}

AUTH_USER_MODEL = "custom.CustomUser"
SUPPRESS_AUTHENTICATION = ENV.SUPPRESS_AUTHENTICATION

# Host destinations the (app-agnostic) sign-in code hands control to, resolved via `resolve_url`.
# This is the contract that keeps `user`/`organization`/`custom` from importing host (`ucfp`) code:
# they read these settings, and the host binds each to one of its own views here.
LOGIN_REDIRECT_URL = 'dashboard'         # where a signed-in user lands (their app home)
GUEST_START_URL = 'flow_profile'         # where a freshly-created Guest goes to start entering data
SIGNIN_COLLISION_URL = 'signin_collision'   # reconcile entry when a Guest signs into an existing account

# Keys and cipher for the encrypted model fields (see common.encrypted_fields).
# Empty keys mean "not configured" -- the fields fail closed on first use rather
# than store plaintext; every real deployment sets UCFP_FIELD_ENCRYPTION_KEY.
FIELD_ENCRYPTION_KEYS = ENV.FIELD_ENCRYPTION_KEYS
FIELD_ENCRYPTION_CODEC = 'fernet'

# Unguessable URL prefix for the admin-only entry points (admin/, env/), set on
# public deployments via UCFP_SECRET_URL_PREFIX_UUID. Blank in the default
# self-host setup, leaving the routes at /admin/ and /env/. See ucfp/urls.py.
SECRET_URL_PREFIX = ENV.SECRET_URL_PREFIX

# Settings whose values may be exposed to templates via the {% settings_value %}
# tag (common/templatetags/common_tags.py). Keep minimal -- never add secrets.
TEMPLATE_VISIBLE_SETTINGS = ['SITE_NAME']

# Optional Datadog metrics (common/metrics.py). Off by default; requires the
# optional `datadog` package when enabled.
METRICS_ENABLED = False

# ====================
# Transactional Emails

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# ENV.EMAIL_SUBJECT_PREFIX already carries its trailing-space separator.
EMAIL_SUBJECT_PREFIX = ENV.EMAIL_SUBJECT_PREFIX
DEFAULT_FROM_EMAIL = ENV.DEFAULT_FROM_EMAIL
SERVER_EMAIL = ENV.SERVER_EMAIL
FROM_EMAIL_NAME = SITE_NAME

# Where abuse-prevention admin alerts are sent. Reuses the server/ops address by
# default; a deployment can point it at a distinct inbox by overriding this.
ADMIN_ALERT_EMAIL = SERVER_EMAIL

# Normal Settings
EMAIL_HOST = ENV.EMAIL_HOST
try:
    EMAIL_PORT = ENV.EMAIL_PORT
except (TypeError, ValueError):
    EMAIL_PORT = 587
    
EMAIL_HOST_USER = ENV.EMAIL_HOST_USER
EMAIL_HOST_PASSWORD = ENV.EMAIL_HOST_PASSWORD
EMAIL_TIMEOUT = 10  # In seconds

EMAIL_USE_TLS = ENV.EMAIL_USE_TLS
EMAIL_USE_SSL = ENV.EMAIL_USE_SSL
    
# Needed when sending emails in background tasks since HttpRequest not
# available. Override this for development/testing/staging.
#
BASE_URL_FOR_EMAIL_LINKS = f'http://{SITE_DOMAIN}'


# ====================
# Development-related Settings
# (override in development.py, not here)


# In development and debugging, because the background javascript is
# polling frequently, this clutters up the console with log messages which
# makes it hard to sort through the other things logging.  This allows
# suppressing those via a logging filter.  This only applies if the logging
# configuration is using that special filter (in common.log_filters).
#
SUPPRESS_SELECT_REQUEST_ENDPOINTS_LOGGING = True

# In development and debugging, the debug noise and interference from the
# background periodic monitoring tasks can be a problem. This gives a way
# to turn them off with one setting.
#
SUPPRESS_MONITORS = False
