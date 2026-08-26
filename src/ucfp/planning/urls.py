"""`/plan/` -- the planning features.

All four perspectives are first-class from day one; the three unbuilt ones render a "coming soon"
placeholder. The feature-agnostic run views live under `/run/` (see `run_urls.py`).
"""
from django.urls import path

from . import views

urlpatterns = [
    path( 'financial-forecast/', views.FinancialForecastView.as_view(), name = 'financial_forecast' ),
    path( 'financial-forecast/runs/<uuid:run_uuid>/delete/', views.DeleteRunView.as_view(),
          name = 'delete_run' ),
    # The workspace is org-level (one exploration per org), so it lives at a uuid-less URL and reads the
    # current exploration; `enter/` initialises-or-resumes from the hub's scenario, then redirects here.
    path( 'financial-forecast/explore/', views.ExploreView.as_view(), name = 'explore' ),
    path( 'financial-forecast/explore/enter/', views.EnterExploreView.as_view(), name = 'explore_enter' ),
    path( 'financial-forecast/explore/restart/', views.ExploreRestartView.as_view(), name = 'explore_restart' ),
    path( 'financial-forecast/explore/plans/', views.ExplorePlansAutosaveView.as_view(),
          name = 'explore_save_plans' ),
    path( 'financial-forecast/explore/assumptions/',
          views.ExploreAssumptionsAutosaveView.as_view(), name = 'explore_save_assumptions' ),
    path( 'financial-forecast/explore/curate/', views.ExploreCurationView.as_view(),
          name = 'explore_curate' ),
    path( 'financial-forecast/explore/save-dialog/', views.ExploreSaveModalView.as_view(),
          name = 'explore_save_dialog' ),
    path( 'financial-forecast/explore/save/', views.SaveView.as_view(), name = 'explore_save' ),
    path( 'financial-forecast/explore/keep-run/', views.KeepRunView.as_view(),
          name = 'explore_keep_run' ),
    path( 'financial-forecast/explore/reset/', views.ResetExploreView.as_view(),
          name = 'explore_reset' ),
]
