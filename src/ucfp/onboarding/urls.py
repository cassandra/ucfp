"""Onboarding: the guest/new-user experience layer over the domain -- currently the sign-in collision
reconcile (the read-only example/preview views land here next)."""
from django.urls import path

from . import views


urlpatterns = [

    path( 'signin-collision',
          views.SigninCollisionView.as_view(),
          name = 'signin_collision' ),

    path( 'start-tour', views.StartTourView.as_view(), name = 'start_tour' ),
    path( 'add-my-data', views.AddMyDataView.as_view(), name = 'add_my_data' ),
    path( 'go-to-dashboard', views.GoToOwnDashboardView.as_view(), name = 'go_to_dashboard' ),
    path( 'tour/profile/<str:section>/', views.TourProfileView.as_view(), name = 'tour_profile' ),
    path( 'tour/scenario/<str:section>/', views.TourScenarioView.as_view(), name = 'tour_scenario' ),
    path( 'tour/forecast/', views.TourForecastView.as_view(), name = 'tour_forecast' ),
    path( 'tour/tax-details/', views.TourTaxDetailsView.as_view(), name = 'tour_tax_details' ),
]
