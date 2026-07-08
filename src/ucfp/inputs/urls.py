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
    path( 'interview/debt/list/', views.DebtsView.as_view(), name = 'debts' ),
    path( 'interview/debt/plan/', views.DebtPlanView.as_view(), name = 'debt_plan' ),
    path( 'interview/debt/cards/', views.CreditCardView.as_view(), name = 'credit_card_plan' ),
    path( 'interview/external-factors/edit/', views.ExternalFactorsView.as_view(),
          name = 'external_factors' ),
    path( 'interview/properties/residence/', views.ResidenceView.as_view(), name = 'residence' ),
    path( 'interview/properties/possessions/', views.PossessionsView.as_view(),
          name = 'possessions' ),
    path( 'interview/properties/rentals/add/', views.RentalFormView.as_view(), name = 'rental_add' ),
    path( 'interview/properties/rentals/<str:handle>/delete/',
          views.RentalDeleteView.as_view(), name = 'rental_delete' ),
    path( 'interview/properties/rentals/<str:handle>/', views.RentalFormView.as_view(),
          name = 'rental_edit' ),
    path( 'interview/properties/second-homes/add/', views.SecondHomeFormView.as_view(),
          name = 'second_home_add' ),
    path( 'interview/properties/second-homes/<str:handle>/delete/',
          views.SecondHomeDeleteView.as_view(), name = 'second_home_delete' ),
    path( 'interview/properties/second-homes/<str:handle>/', views.SecondHomeFormView.as_view(),
          name = 'second_home_edit' ),
    # A specific segment (not a spending group), so it must precede the group catch-all below and
    # not collide with the 'auto' expense category's own `spending/auto/` group route.
    path( 'interview/spending/auto-purchases/', views.AutoPlanView.as_view(),
          name = 'auto_purchases' ),
    path( 'interview/spending/<str:group>/', views.SpendingGroupView.as_view(),
          name = 'spending_group' ),
    path( 'interview/events/add/<str:kind>/', views.EventAddView.as_view(), name = 'event_add' ),
    path( 'interview/events/delete/<int:index>/', views.EventDeleteView.as_view(),
          name = 'event_delete' ),
]
