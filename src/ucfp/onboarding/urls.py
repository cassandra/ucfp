"""Onboarding: the guest/new-user experience layer over the domain -- currently the sign-in collision
reconcile (the read-only sample/preview views land here next)."""
from django.urls import path

from . import views


urlpatterns = [

    path( 'signin-collision',
          views.SigninCollisionView.as_view(),
          name = 'signin_collision' ),
]
