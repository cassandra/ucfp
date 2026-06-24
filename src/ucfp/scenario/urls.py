from django.urls import path

from . import views

urlpatterns = [
    path( '', views.ScenarioHomeView.as_view(), name = 'scenario_home' ),
    path( '<uuid:scenario_uuid>/', views.ScenarioDetailView.as_view(), name = 'scenario_detail' ),
]
