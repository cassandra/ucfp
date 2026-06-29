"""`/plan/` -- the planning features.

All four perspectives are first-class from day one; the three unbuilt ones render a "coming soon"
placeholder. The interview moved to `/inputs/` and the run views to `/run/` (see `run_urls.py`).
"""
from django.urls import path

from . import views

urlpatterns = [
    path( 'financial-forecast/', views.FinancialForecastView.as_view(), name = 'financial_forecast' ),
    path( 'retirement-timing/',
          views.ComingSoonView.as_view( feature_key = 'retirement_timing' ),
          name = 'retirement_timing' ),
    path( 'social-security/',
          views.ComingSoonView.as_view( feature_key = 'social_security' ),
          name = 'social_security' ),
    path( 'cash-flow-planning/',
          views.ComingSoonView.as_view( feature_key = 'cash_flow_planning' ),
          name = 'cash_flow_planning' ),
]
