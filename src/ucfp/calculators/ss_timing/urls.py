"""The Social Security timing calculator's routes -- login-free (see the app urls)."""
from django.urls import path

from . import views

app_name = 'ss_timing'

urlpatterns = [
    path( '', views.InputsView.as_view(), name = 'inputs' ),
    path( 'results/', views.ResultsView.as_view(), name = 'results' ),
]
