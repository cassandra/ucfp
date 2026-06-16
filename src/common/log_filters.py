"""
Logging filters used by the project's LOGGING configuration.

All log filters live here (organized by function): they are referenced from
settings by dotted path, e.g. ``common.log_filters.SuppressPipelineTemplateVarsFilter``.
"""
import logging
import re

from django.conf import settings
from django.urls import resolve


class SuppressPipelineTemplateVarsFilter(logging.Filter):
    """Filter out Django Pipeline template variable lookup errors."""

    PIPELINE_VARIABLES = {
        'media', 'title', 'charset', 'defer', 'async', 'rel'
    }

    def filter(self, record):
        # Check the log record for Pipeline-related template errors
        if hasattr(record, 'msg'):
            msg = str(record.msg)

            # Check for Pipeline template path in the message
            if "pipeline/" in msg:
                return False

            # Check for common Pipeline variable lookup errors
            if "Failed lookup for key" in msg:
                # Extract variable name and check if it's a Pipeline variable
                match = re.search(r"Failed lookup for key \[(\w+)\]", msg)
                if match and match.group(1) in self.PIPELINE_VARIABLES:
                    return False

            # Check for Pipeline variable resolution errors
            if "Exception while resolving variable" in msg:
                for var_name in self.PIPELINE_VARIABLES:
                    if f"variable '{var_name}'" in msg:
                        return False

        # Also check if the record has template information
        if hasattr(record, 'exc_info') and record.exc_info:
            # Look at the traceback to see if it mentions pipeline templates
            import traceback
            tb_str = ''.join(traceback.format_exception(*record.exc_info))
            if 'pipeline/' in tb_str:
                return False

        return True


class SuppressSelectRequestEndpointsFilter(logging.Filter):
    """Suppress request-log lines for selected endpoints, matched by URL *name*
    (resolved from the request path) rather than by hardcoded paths.

    Populate URL_NAMES_TO_FILTER with the URL names of noisy endpoints -- e.g. a
    health-check or status poll that the frontend hits frequently -- to keep
    them out of the request log. Gated by the
    SUPPRESS_SELECT_REQUEST_ENDPOINTS_LOGGING setting so it can be toggled per
    environment; if that setting is absent the filter does nothing.
    """

    # Project-specific: URL names whose request logs should be suppressed.
    URL_NAMES_TO_FILTER = set()

    def filter( self, record ):
        if not getattr( settings, 'SUPPRESS_SELECT_REQUEST_ENDPOINTS_LOGGING', False ):
            return True
        if not self.URL_NAMES_TO_FILTER:
            return True
        try:
            if not hasattr(record, "args") or ( len(record.args) < 1 ):
                return True

            request_line = record.args[0]

            if not isinstance( request_line, str ):
                # Sometimes it appears to be a PosixPath, but for requests it is a string.
                return True

            match = re.match( r'^[A-Z]+ (/[^ ?]*)', request_line )
            if not match:
                return True

            request_path = match.group(1)
            resolved = resolve( request_path )
            if resolved.url_name in self.URL_NAMES_TO_FILTER:
                return False

        except Exception:
            pass

        return True
