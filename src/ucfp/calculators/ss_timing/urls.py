"""The Social Security timing calculator's routes -- login-free (see the app urls). The estimator's
`index` is the person its confirmed estimate writes back to (0 the primary, 1 the partner)."""
from django.urls import path

from . import views

app_name = 'ss_timing'

urlpatterns = [
    path( '', views.InputsView.as_view(), name = 'inputs' ),
    path( 'results/', views.ResultsView.as_view(), name = 'results' ),
    path( 'results/detail/<str:combo>/', views.StrategyDetailView.as_view(), name = 'detail' ),
    path( 'estimate/<int:index>/', views.BenefitEstimatorModalView.as_view(), name = 'estimate' ),
    path( 'estimate/<int:index>/apply/', views.BenefitEstimateApplyView.as_view(),
          name = 'estimate_apply' ),
]
