"""
Auto-discovery for the /testing hub.

Any installed app can contribute UI testing pages and/or development tools by
following a filename convention -- no central registration. An app participates
simply by providing one or both of:

    {app}/tests/ui/urls.py        -> mounted at /testing/ui/{app}/
    {app}/tests/devtools/urls.py  -> mounted at /testing/devtools/{app}/

The functions here scan the installed apps for those modules. A missing module
just means the app doesn't participate; a module that exists but fails to import
is logged and skipped so one broken contributor cannot take down the whole hub.
"""
import logging

from django.apps import apps

from common.module_utils import import_module_safe

logger = logging.getLogger(__name__)


def discover_test_modules( submodule ):
    """
    Yield ``(short_name, module)`` for every installed app that provides a
    ``{app}.tests.{submodule}.urls`` module. ``submodule`` is 'ui' or 'devtools'.
    """
    for app_config in apps.get_app_configs():
        short_name = app_config.name.split('.')[-1]
        module_name = f'{app_config.name}.tests.{submodule}.urls'
        try:
            module = import_module_safe( module_name = module_name )
        except Exception:
            logger.exception( f'Problem loading {submodule} tests for {short_name}.' )
            continue
        if module:
            yield short_name, module
        continue
