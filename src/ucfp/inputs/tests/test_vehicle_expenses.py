"""The Vehicle running-costs pane totals the per-car costs (#182 Phase 1).

A single per-vehicle yearly figure: each running-cost row annualized to a yearly amount and summed. It
is deliberately a per-car total (materialization scales it across the owned fleet over time), shown in
the pane footer under the id the antinode `replace_map` targets after a silent save.
"""
from decimal import Decimal

from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from common.recurrence import Duration, TimeUnit

from organization.models import Organization

from ucfp.environment.constants import AppConst
from ucfp.inputs.expenses import ordered_catalog
from ucfp.inputs.models import PlansRecord
from ucfp.inputs.plans.repository import save_plans
from ucfp.inputs.plans.schemas import Plans, VehiclePlan, VehicleRunningCost
from ucfp.inputs.vehicle_expenses import VehicleExpensesForm
from ucfp.inputs.views import VehicleExpensesView
from ucfp.parameter_sets.enums import ExpenseClass
from ucfp.session_state import SessionState

_MONTHLY = Duration( 1, TimeUnit.MONTH )


def _vehicle_catalog_rows() -> list:
    return [ row for row in ordered_catalog() if row.expense_class is ExpenseClass.VEHICLE ]


def _cost( catalog_row, amount : Decimal ) -> VehicleRunningCost:
    return VehicleRunningCost(
        name = catalog_row.name, handle = catalog_row.handle,
        expense_tax_class = catalog_row.expense_tax_class, interval = _MONTHLY, amount = amount )


def _plans_with_every_cost_at( amount : Decimal ) -> Plans:
    """Plans whose every vehicle running cost is set to `amount`/month, so the total is fully determined
    by the test (no catalog default amount leaks in)."""
    rows = [ _cost( row, amount ) for row in _vehicle_catalog_rows() ]
    return Plans( vehicle_plan = VehiclePlan( running_costs = rows ) )


class VehicleRunningCostsTotalTest( TestCase ):

    def setUp( self ):
        call_command( 'seed_parameter_sets' )       # the vehicle running-cost catalog rows

    def test_total_is_the_annualized_sum_of_the_per_car_costs( self ):
        count = len( _vehicle_catalog_rows() )
        form  = VehicleExpensesForm( plans = _plans_with_every_cost_at( Decimal( '50' ) ) )
        self.assertEqual( form.total.amount, Decimal( '50' ) * 12 * count )   # $600/car/yr per cost

    def test_total_row_renders_under_the_replace_target_id( self ):
        form = VehicleExpensesForm( plans = _plans_with_every_cost_at( Decimal( '50' ) ) )
        html = render_to_string(
            VehicleExpensesView.template,
            { VehicleExpensesView.context_name: form, 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertIn( f'id="{VehicleExpensesForm.TOTAL_ID}"', html )     # else the replace can't land
        self.assertIn( '>Total</th>', html )                              # the total row's leading label


class VehicleTotalsPushTest( TestCase ):
    """The view recomputes the total from the just-persisted plans and hands it back as an antinode
    replace fragment -- the server-computed push that keeps the on-page total live after a silent edit."""

    def setUp( self ):
        call_command( 'seed_parameter_sets' )
        self.organization = Organization.objects.create( name = 'Org' )

    def _request( self ):
        request = RequestFactory().get( '/inputs/interview/vehicle-expenses/costs/edit/' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        return request

    def test_totals_fragments_pushes_the_total_keyed_by_its_id( self ):
        save_plans( PlansRecord.objects.create( organization = self.organization, label = 'P' ),
                    _plans_with_every_cost_at( Decimal( '50' ) ) )
        fragments = VehicleExpensesView().totals_fragments( self._request() )
        self.assertIn( VehicleExpensesForm.TOTAL_ID, fragments )
        self.assertIn( f'id="{VehicleExpensesForm.TOTAL_ID}"', fragments[ VehicleExpensesForm.TOTAL_ID ] )
