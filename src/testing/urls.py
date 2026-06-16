from django.urls import include, path

from . import views


urlpatterns = [

    path( '', views.TestingHomeView.as_view(), name = 'testing_home' ),

    path( 'ui/', include( 'testing.ui.urls' )),
    path( 'devtools/', include( 'testing.devtools.urls' )),

]
