"""`/inputs/` -- the inputs area: the hub, the three editable flows, and the guided interview.

All served by this app's own views. The interview's section routes keep stable `name`s
(`interview_section`, `residence`, ...) so existing `{% url %}` references resolve unchanged; the
flow is derived from the section, so the section URL needs no flow segment.
"""
from django.urls import path

from . import views

urlpatterns = [
    path( '', views.InputsHubView.as_view(), name = 'inputs_home' ),

    # The three input flows, each editable on its own (the guided interview chains them).
    path( 'profile/', views.FlowEntryView.as_view( flow = 'profile' ), name = 'flow_profile' ),
    path( 'plans/', views.FlowEntryView.as_view( flow = 'plans' ), name = 'flow_plans' ),
    path( 'assumptions/', views.FlowEntryView.as_view( flow = 'assumptions' ),
          name = 'flow_assumptions' ),

    # Guided interview + the per-section editors.
    path( 'interview/', views.InterviewHomeView.as_view(), name = 'interview_home' ),
    path( 'interview/<str:section>/', views.InterviewView.as_view(), name = 'interview_section' ),
    path( 'interview/income/table/', views.IncomeTableView.as_view(), name = 'income_table' ),
    path( 'interview/properties/residence/', views.ResidenceView.as_view(), name = 'residence' ),
    path( 'interview/properties/rentals/add/', views.RentalFormView.as_view(), name = 'rental_add' ),
    path( 'interview/properties/rentals/<str:handle>/delete/',
          views.RentalDeleteView.as_view(), name = 'rental_delete' ),
    path( 'interview/properties/rentals/<str:handle>/', views.RentalFormView.as_view(),
          name = 'rental_edit' ),
    path( 'interview/spending/<str:group>/', views.SpendingGroupView.as_view(),
          name = 'spending_group' ),
    path( 'interview/events/add/<str:kind>/', views.EventAddView.as_view(), name = 'event_add' ),
    path( 'interview/events/delete/<int:index>/', views.EventDeleteView.as_view(),
          name = 'event_delete' ),
]
