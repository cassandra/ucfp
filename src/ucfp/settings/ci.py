# -*- coding: utf-8 -*-
from .base import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Scratch collectstatic target, namespaced by the package dir name (BASE_DIR.name)
# so it follows the package rename and never collides with sibling projects.
STATIC_ROOT = f'/tmp/{BASE_DIR.name}/static'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'ucfp': {
            'handlers': ['console' ],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

BASE_URL_FOR_EMAIL_LINKS = 'http://127.0.0.1:8666/'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

SUPPRESS_SELECT_REQUEST_ENDPOINTS_LOGGING = True
SUPPRESS_MONITORS = True
