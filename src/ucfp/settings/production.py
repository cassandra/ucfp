# -*- coding: utf-8 -*-
from .base import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": 'pipeline.storage.PipelineManifestStorage',
    },
}
STATIC_ROOT = '/src/static'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {module} {process:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'ERROR',
        },
        'ucfp': {
            'handlers': ['console' ],
            'level': 'INFO',
        },
    },
}

BASE_URL_FOR_EMAIL_LINKS = f'https://{SITE_DOMAIN}'

# Transactional email. The cloud host (DigitalOcean) blocks outbound SMTP, so the
# public deployment sends through Resend's API via Anymail instead of the SMTP
# backend base.py configures. The key comes from UCFP_EMAIL_API_KEY.
#
# Deliberately no startup validation of the key: a missing or wrong key is a send
# concern, surfaced where mail is actually sent (EmailSender.is_email_configured
# gates the sign-in UI on it, and a bad key fails the send itself with a logged
# error) -- not a boot-time failure that would also take down the marketing pages
# that anonymous visitors can still reach without email.
INSTALLED_APPS += [ 'anymail' ]
EMAIL_BACKEND = 'anymail.backends.resend.EmailBackend'
ANYMAIL = { 'RESEND_API_KEY': ENV.EMAIL_API_KEY }
