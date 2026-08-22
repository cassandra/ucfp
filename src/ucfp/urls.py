from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import include, path, re_path
from django.views.generic.base import RedirectView, TemplateView

from . import views

urlpatterns = [

    # Favicons are tricky to get 100% right and some browsers / crawlers will
    # request /favicon.ico at the site root no matter what <link> tags say.
    path( 'favicon.ico',
          RedirectView.as_view( url = staticfiles_storage.url('favicon.ico'),
                                permanent = False ),
          name = 'favicon' ),

    re_path( r'^(?P<filename>(service-worker.js))$',
             views.home_javascript_files, name = 'home-javascript-files' ),

    path( 'manifest.json', views.ManifestView.as_view(), name = 'manifest' ),

    path( f'{settings.SECRET_URL_PREFIX}admin/', admin.site.urls ),

    path( '', views.HomeView.as_view(), name = 'home' ),
    path( 'index.html', views.HomeView.as_view(), name = 'home_index' ),
    path( 'dashboard', views.DashboardView.as_view(), name = 'dashboard' ),
    path( 'health', views.HealthView.as_view(), name = 'health' ),

    # Onboarding page for a visitor with no account (login-free): Explain introduces the app and funnels
    # into the tour ("Take a Tour") or the convert-to-Guest graduation ("Add my data").
    path( 'explain', TemplateView.as_view( template_name = 'pages/explain.html' ), name = 'explain' ),

    # Public content pages (login-free; linked from the shared footer).
    path( 'about', TemplateView.as_view( template_name = 'pages/about.html' ), name = 'about' ),
    path( 'contact', TemplateView.as_view( template_name = 'pages/contact.html' ), name = 'contact' ),
    path( 'privacy', TemplateView.as_view( template_name = 'pages/privacy.html' ), name = 'privacy' ),
    path( 'privacy/accept', views.PrivacyAcceptView.as_view(), name = 'privacy_accept' ),
    path( 'terms', TemplateView.as_view( template_name = 'pages/terms.html' ), name = 'terms' ),

    path( f'{settings.SECRET_URL_PREFIX}env/', include( 'ucfp.environment.urls' )),

    # Email unsubscribe landing (login-free, hash-protected).
    path( 'notify/', include( 'notify.urls' )),

    path( 'user/', include( 'user.urls' )),

    path( 'organization/', include( 'organization.urls' )),

    path( 'welcome/', include( 'ucfp.onboarding.urls' )),

    path( 'inputs/', include( 'ucfp.inputs.urls' )),
    path( 'plan/', include( 'ucfp.planning.urls' )),
    path( 'run/', include( 'ucfp.planning.run_urls' )),

    # Custom error pages
    path( '400.html', views.bad_request_response, name = 'bad_request' ),
    path( '403.html', views.not_authorized_response, name = 'not_authorized' ),
    path( '404.html', views.page_not_found_response, name = 'page_not_found' ),
    path( '405.html', views.method_not_allowed_response, name = 'method_not_allowed' ),
    path( '500.html', views.internal_error_response, name = 'internal_error' ),
    path( '503.html', views.transient_error_response, name = 'transient_error' ),

]

urlpatterns += static( settings.MEDIA_URL, document_root = settings.MEDIA_ROOT )

# Development-only testing hub (UI testing pages + devtools). The `testing` app
# is only installed under the development settings; gate the URLs to match.
if settings.DEBUG:
    urlpatterns += [
        path( 'testing/', include( 'testing.urls' )),
    ]

handler404 = 'ucfp.views.custom_404_handler'
