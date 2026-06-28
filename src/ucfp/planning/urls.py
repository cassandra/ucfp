from django.urls import path

from . import views

urlpatterns = [
    path( 'retirement/', views.RetirementPlanningView.as_view(), name = 'retirement_planning' ),
    path( 'interview/', views.InterviewHomeView.as_view(), name = 'interview_home' ),
    path( 'interview/<str:section>/', views.InterviewView.as_view(), name = 'interview_section' ),
    path( 'interview/income/table/', views.IncomeTableView.as_view(), name = 'income_table' ),
    path( 'interview/properties/residence/', views.ResidenceView.as_view(), name = 'residence' ),
    path( 'interview/properties/rentals/add/', views.RentalFormView.as_view(), name = 'rental_add' ),
    path( 'interview/properties/rentals/<str:handle>/delete/', views.RentalDeleteView.as_view(),
          name = 'rental_delete' ),
    path( 'interview/properties/rentals/<str:handle>/', views.RentalFormView.as_view(),
          name = 'rental_edit' ),
    path( 'interview/spending/<str:group>/', views.SpendingGroupView.as_view(),
          name = 'spending_group' ),
    path( 'interview/events/add/<str:kind>/', views.EventAddView.as_view(), name = 'event_add' ),
    path( 'interview/events/delete/<int:index>/', views.EventDeleteView.as_view(),
          name = 'event_delete' ),
    path( 'run/<uuid:run_uuid>/', views.RunResultsView.as_view(), name = 'run_results' ),
]
