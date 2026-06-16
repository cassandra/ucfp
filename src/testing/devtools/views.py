from django.shortcuts import render
from django.views.generic import View

from testing.discovery import discover_test_modules


class DevtoolsHomeView( View ):

    def get( self, request, *args, **kwargs ):
        app_url_list = [
            ( short_name, f'{short_name}/' )
            for short_name, _module in discover_test_modules( 'devtools' )
        ]
        context = {
            'app_url_list': app_url_list,
        }
        return render( request, 'testing/devtools/pages/testing_devtools_home.html', context )
