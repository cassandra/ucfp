# Optional Datadog (dogstatsd) metrics.
#
# Metrics are OFF by default. Unless settings.METRICS_ENABLED is true AND the
# optional ``datadog`` package is installed, every function here is a silent
# no-op -- so callers never have to guard their metric calls and the project
# carries no hard dependency on datadog.
#
# To enable: ``pip install datadog``, set ``METRICS_ENABLED = True``, and
# (optionally) ``DATADOG_AGENT_HOST`` / ``DATADOG_AGENT_PORT`` /
# ``METRICS_NAMESPACE``.
#
# See: https://datadogpy.readthedocs.io/en/latest/
from functools import wraps
import logging
import time

from django.conf import settings

logger = logging.getLogger( __name__ )


class _NoOpStatsd:
    """Stand-in for the datadog statsd client when metrics are disabled or the
    datadog package is unavailable. Silently accepts any statsd call."""

    def __getattr__( self, _name ):
        def _noop( *args, **kwargs ):
            return None
        return _noop


def _build_statsd():
    if not getattr( settings, 'METRICS_ENABLED', False ):
        return _NoOpStatsd()

    try:
        from datadog import initialize, statsd
    except ImportError:
        logger.warning( 'settings.METRICS_ENABLED is set but the "datadog" package '
                        'is not installed; metrics will be no-ops.' )
        return _NoOpStatsd()

    if getattr( settings, 'UNIT_TESTING', False ):
        from unittest.mock import Mock
        statsd.socket = Mock()

    initialize(
        statsd_host          = getattr( settings, 'DATADOG_AGENT_HOST', 'localhost' ),
        statsd_port          = getattr( settings, 'DATADOG_AGENT_PORT', 8125 ),
        statsd_namespace     = getattr( settings, 'METRICS_NAMESPACE', '' ),
        statsd_constant_tags = [ f'environment:{getattr( settings, "ENVIRONMENT", "unknown" )}' ],
    )
    return statsd


# Resolved once at import time from the active settings.
statsd = _build_statsd()


def timed( method ):
    """ Decorator for timing function/method execution times """

    @wraps( method )
    def wrapper( *args, **kwargs ):
        start_time = time.time()
        result = method( *args, **kwargs )
        end_time = time.time()
        elapsed_time_ms = ( end_time - start_time )

        statsd.timing( 'timing',
                       elapsed_time_ms,
                       tags = [ f'name:{method.__name__}' ] )

        logger.debug( f'TIMED: {method.__name__} : {elapsed_time_ms:.2f} ms' )
        return result
    return wrapper


def increment( name, tags = None ):
    statsd.increment( name, tags = tags )
    return


def decrement( name, tags = None ):
    statsd.decrement( name, tags = tags )
    return


def gauge( name, value, tags = None ):
    statsd.gauge( name, value, tags = tags )
    return


def histogram( name, value, tags = None ):
    statsd.histogram( name, value, tags = tags )
    return


def event( title, text, alert_type = 'info', tags = None ):
    assert alert_type in { 'error', 'warning', 'success', 'info' }
    statsd.event( title, text, alert_type = alert_type, tags = tags )
    return


def exception( exception : Exception ):
    statsd.increment( 'exception', tags = [ f'name:{type(exception)}' ] )
    return


def error( label : str ):
    statsd.increment( 'error', tags = [ f'name:{label}' ] )
    return


def warning( label : str ):
    statsd.increment( 'warning', tags = [ f'name:{label}' ] )
    return


def increment_event( label : str ):
    statsd.increment( 'event', tags = [ f'name:{label}' ] )
    return
