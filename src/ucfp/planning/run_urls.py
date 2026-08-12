"""`/run/` -- the shared projection-run views.

A `ProjectionRunRecord` is shown in the context of the feature that produced it, but the drill-down
itself is feature-agnostic and lives outside `/plan/`, so any feature can reuse it.
"""
from django.urls import path

from . import views

urlpatterns = [
    path( '<uuid:run_uuid>/', views.RunResultsView.as_view(), name = 'run_results' ),
    path( '<uuid:run_uuid>/rename/', views.RenameRunView.as_view(), name = 'rename_run' ),
    path( '<uuid:run_uuid>/discard-confirm/', views.RunDiscardConfirmView.as_view(),
          name = 'run_discard_confirm' ),
    path( '<uuid:run_uuid>/books/', views.ProjectionRunBooksTableView.as_view(),
          name = 'run_books_table' ),
    path( '<uuid:run_uuid>/books/account/<uuid:account_uuid>/journal/',
          views.BooksTableJournalView.as_view(), name = 'books_journal' ),
]
