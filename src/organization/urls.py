from django.urls import path

from . import views

urlpatterns = [
    path( 'settings/', views.OrganizationSettingsView.as_view(), name = 'organization_settings' ),

    path( 'households/<uuid:organization_uuid>/switch',
          views.OrganizationSwitchView.as_view(), name = 'organization_switch' ),

    path( 'account/delete/confirm',
          views.AccountDeleteConfirmView.as_view(), name = 'account_delete_confirm' ),
    path( 'account/delete', views.AccountDeleteView.as_view(), name = 'account_delete' ),

    path( 'households/<uuid:organization_uuid>/delete/confirm',
          views.OrganizationDeleteConfirmView.as_view(), name = 'organization_delete_confirm' ),
    path( 'households/<uuid:organization_uuid>/delete',
          views.OrganizationDeleteView.as_view(), name = 'organization_delete' ),

    path( 'households/<uuid:organization_uuid>/leave/confirm',
          views.OrganizationLeaveConfirmView.as_view(), name = 'organization_leave_confirm' ),
    path( 'households/<uuid:organization_uuid>/leave',
          views.OrganizationLeaveView.as_view(), name = 'organization_leave' ),
]
