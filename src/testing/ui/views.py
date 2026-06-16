from django.shortcuts import render
from django.views.generic import View

from testing.discovery import discover_test_modules


class TestingUiHomeView( View ):

    def get( self, request, *args, **kwargs ):
        app_url_list = [
            ( short_name, f'{short_name}/' )
            for short_name, _module in discover_test_modules( 'ui' )
        ]
        context = {
            'app_url_list': app_url_list,
        }
        return render( request, 'testing/ui/pages/testing_ui_home.html', context )
