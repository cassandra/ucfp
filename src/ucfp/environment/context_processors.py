from django.conf import settings

from .client import ClientConfig
from .constants import AppConst


def client_config(request):
    """
    Provides client-side configuration to templates.

    Creates a structured configuration object that the base template emits as
    the JavaScript global ``window.__APP_CONFIG__`` -- a single source of truth
    for client configuration, relayed to other JS modules via ``App.config``
    (static/js/main.js).

    Fails fast on missing required data - no masking of interface problems.

    Returns:
        dict: Context variables for templates
    """
    config = ClientConfig(
        DEBUG = settings.DEBUG,
        ENVIRONMENT = settings.ENV.environment_name,
        VERSION = settings.ENV.VERSION,
    )

    return {
        'app_client_config': config
    }


def shared_constants(request):
    """
    Injects the AppConst class so templates can reference shared client/server
    constants as ``{{ AppConst.NAME }}``. pages/base.html serializes the same
    class into the ``window.AppConst`` JavaScript global -- a single source of
    truth for both sides.
    """
    return {
        'AppConst': AppConst,
    }
