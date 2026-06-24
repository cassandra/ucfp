from django.urls import path

from . import views

urlpatterns = [
    path( '', views.ProfileHomeView.as_view(), name = 'profile_home' ),
    path( '<uuid:profile_uuid>/', views.ProfileDetailView.as_view(), name = 'profile_detail' ),
]
