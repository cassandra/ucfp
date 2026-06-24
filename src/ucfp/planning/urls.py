from django.urls import path

from . import views

urlpatterns = [
    path( 'retirement/', views.RetirementPlanningView.as_view(), name = 'retirement_planning' ),
    path( 'run/<uuid:run_uuid>/', views.RunResultsView.as_view(), name = 'run_results' ),
]
