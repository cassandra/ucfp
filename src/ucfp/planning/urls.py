"""`/plan/` -- the planning features.

All four perspectives are first-class from day one; the three unbuilt ones render a "coming soon"
placeholder. The feature-agnostic run views live under `/run/` (see `run_urls.py`).
"""
from django.urls import path

from . import views

urlpatterns = [
    path( 'financial-forecast/', views.FinancialForecastView.as_view(), name = 'financial_forecast' ),
    path( 'financial-forecast/explore/enter/', views.EnterExploreView.as_view(), name = 'explore_enter' ),
    path( 'financial-forecast/explore/<uuid:scenario>/', views.ExploreView.as_view(), name = 'explore' ),
    path( 'financial-forecast/explore/<uuid:scenario>/plans/', views.ExplorePlansAutosaveView.as_view(),
          name = 'explore_save_plans' ),
    path( 'financial-forecast/explore/<uuid:scenario>/assumptions/',
          views.ExploreAssumptionsAutosaveView.as_view(), name = 'explore_save_assumptions' ),
    path( 'financial-forecast/explore/<uuid:scenario>/update-scenario/', views.UpdateScenarioView.as_view(),
          name = 'explore_update_scenario' ),
    path( 'financial-forecast/explore/<uuid:scenario>/save-scenario/', views.SaveScenarioView.as_view(),
          name = 'explore_save_scenario' ),
    path( 'financial-forecast/explore/<uuid:scenario>/keep-run/', views.KeepRunView.as_view(),
          name = 'explore_keep_run' ),
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
