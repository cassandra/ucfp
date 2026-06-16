import os

from django.conf import settings
from django.http import HttpRequest


def is_ajax( request : HttpRequest ):
    return bool( request.headers.get('x-requested-with') == 'XMLHttpRequest' )


def get_absolute_static_path( relative_path ):
    return os.path.join( settings.STATIC_URL, relative_path )
