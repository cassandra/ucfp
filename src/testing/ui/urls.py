from django.urls import include, path, re_path

from testing.discovery import discover_test_modules

from . import views


urlpatterns = [
    path( '', views.TestingUiHomeView.as_view(), name = 'testing_ui_home' ),
]

urlpatterns += [
    re_path( f'{short_name}/', include( module ))
    for short_name, module in discover_test_modules( 'ui' )
]
