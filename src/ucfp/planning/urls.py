from django.urls import path

from . import views

urlpatterns = [
    path( 'retirement/', views.RetirementPlanningView.as_view(), name = 'retirement_planning' ),
    path( 'interview/', views.InterviewHomeView.as_view(), name = 'interview_home' ),
    path( 'interview/<str:section>/', views.InterviewView.as_view(), name = 'interview_section' ),
    path( 'interview/spending/<str:category>/', views.SpendingCategoryView.as_view(),
          name = 'spending_category' ),
    path( 'run/<uuid:run_uuid>/', views.RunResultsView.as_view(), name = 'run_results' ),
]
