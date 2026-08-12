# -*- coding: utf-8 -*-
"""
Local settings for MANUALLY exercising sign-in abuse prevention (issue #158).

Extends development.py (so any dev-specific behavior still applies), then turns
the abuse-prevention machinery ON -- it is off in plain development -- and makes
its effects observable from a terminal:

  - ABUSE_PREVENTION_ENABLED = True
  - a console email backend + placeholder EMAIL_* so sign-in codes, coalesced
    admin alerts, and the List-Unsubscribe header all print to the console (and
    EmailSender.is_email_configured() returns True)
  - deliberately tiny limits so each one is reachable in a few clicks

Requires a real local Redis at 127.0.0.1:6379 -- without it the rate limiter
fails open and nothing throttles.

Run:
    ./src/manage.py runserver --settings=ucfp.settings.test_local_abuse

See docs/dev/testing/test-plan-abuse-prevention.md.
"""
from .development import *

ABUSE_PREVENTION_ENABLED = True

# Print every email (codes, admin alerts, unsubscribe links, headers) to the
# console, and satisfy is_email_configured() with placeholder credentials.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
EMAIL_HOST = 'localhost'
EMAIL_PORT = 25
EMAIL_HOST_USER = 'dev'
DEFAULT_FROM_EMAIL = 'dev@localhost'
SERVER_EMAIL = 'ops@localhost'
ADMIN_ALERT_EMAIL = SERVER_EMAIL

# Small limits so behaviour is reachable by hand.
SIGNIN_PER_IP_LIMIT = 3
SIGNIN_PER_EMAIL_HOURLY_LIMIT = 2
SIGNIN_PER_EMAIL_DAILY_LIMIT = 4
SIGNIN_GLOBAL_LIMIT = 10

SIGNIN_VERIFY_FREE_ATTEMPTS = 1
SIGNIN_VERIFY_FIRST_DELAY_SECS = 3
SIGNIN_VERIFY_MAX_DELAY_SECS = 10
SIGNIN_VERIFY_MAX_FAILURES = 3
SIGNIN_VERIFY_PER_IP_LIMIT = 8
