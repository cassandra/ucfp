# -*- coding: utf-8 -*-
from .base import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Sign-in abuse prevention off in local development, so hammering the sign-in
# flow while iterating never trips a rate limit.
ABUSE_PREVENTION_ENABLED = False

# Development/DEBUG-only testing hub (the /testing UI + devtools auto-discovery).
# Kept out of base INSTALLED_APPS so production carries no trace of it; its URLs
# are likewise mounted only under `if settings.DEBUG` (see ucfp/urls.py).
INSTALLED_APPS += [
    'testing',
]

# Isolate the test suite from real Redis/cache: swaps in fakeredis + LocMemCache
# before any test runs, regardless of which test base class is used.
TEST_RUNNER = 'testing.runner.IsolatedTestRunner'

# Override template options for development debugging
TEMPLATES[0]['OPTIONS'].update({
    'debug': True,
    # 'string_if_invalid': 'INVALID_VARIABLE_%s',
})

# Scratch collectstatic target, namespaced by the package dir name (BASE_DIR.name)
# so it follows the package rename and never collides with sibling projects.
STATIC_ROOT = f'/tmp/{BASE_DIR.name}/static'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    # Since the API status gets polled frequently, this gums up the
    # terminal and makes developing and debugging everything else more
    # unpleasant.
    #
    'filters': {
        'suppress_select_request_endpoints': {
            '()': 'common.log_filters.SuppressSelectRequestEndpointsFilter',
        },
        'suppress_pipeline_template_vars': {
            '()': 'common.log_filters.SuppressPipelineTemplateVarsFilter',
        },
    },
    'formatters': {
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': [ 'suppress_select_request_endpoints' ],
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'django.server': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.db': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'django.core.mail': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
        'django.template': {
            'handlers': ['console'],
            'level': 'INFO',  # INFO (not DEBUG) reduces verbose variable-lookup messages
            'filters': ['suppress_pipeline_template_vars'],
            'propagate': False,
        },
        'common': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'ucfp': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
}

BASE_URL_FOR_EMAIL_LINKS = 'http://127.0.0.1:8666/'

# Uncomment to suppress email sending and write to console.
#
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

SUPPRESS_SELECT_REQUEST_ENDPOINTS_LOGGING = True
SUPPRESS_MONITORS = False
