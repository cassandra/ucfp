from django.urls import path

from . import views

urlpatterns = [
    path( 'settings/', views.OrganizationSettingsView.as_view(), name = 'organization_settings' ),
]
