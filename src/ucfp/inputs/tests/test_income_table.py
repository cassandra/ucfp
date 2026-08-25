"""The income facts pane can re-render its edits: its wrapper carries the antinode swap-target id.

`IncomeTableView` is a `SelfSavingPaneView`, so a save that adds or removes a line re-renders the pane via
antinode's `replace_map` keyed on `IncomeTableView.target`. That swap only lands if the rendered pane
carries a matching `id`. Without it, edits persist but the table never re-renders -- a filled blank row
does not spawn a fresh one, and a remove checkbox does nothing until a full page reload. This pins the
pane's wrapper id to the view's declared target so the two cannot drift apart again.
"""
from datetime import date
from decimal import Decimal

from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from ucfp.accounts.enums import IncomeTaxClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.income import IncomeTableForm
from ucfp.inputs.plans.schemas import IncomeTiming, Plans
from ucfp.inputs.profile.schemas import IncomeFlow, Profile, SubjectProfile
from ucfp.inputs.views import IncomeTableView


class IncomeTablePaneTest( SimpleTestCase ):

    def test_the_pane_carries_the_view_swap_target_id( self ):
        profile = Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ] )
        html = render_to_string(
            IncomeTableView.template,
            { IncomeTableView.context_name: IncomeTableForm( profile = profile ), 'AppConst': AppConst },
            request = RequestFactory().get( '/' ) )
        self.assertIn( f'id="{IncomeTableView.target}"', html )   # else the self-saving re-render can't land


class IncomeRowsetApplyTests( SimpleTestCase ):
    """The general income lines post as parallel getlists; `apply` rebuilds the flows -- minting a handle
    for a new line, keeping an existing one, honouring the household sentinel, dropping an incomplete row,
    and reaping a removed flow's timing. A negative amount is a genuine error the pane re-renders."""

    def _profile( self, *flows ):
        return Profile(
            subjects = [ SubjectProfile( handle = 'you', name = 'You', birthdate = date( 1960, 1, 1 ) ) ],
            income_flows = list( flows ) )

    @staticmethod
    def _post( names, subjects, amounts, handles ):
        data = QueryDict( mutable = True )
        data.setlist( 'income_name', names )
        data.setlist( 'income_subject', subjects )
        data.setlist( 'income_amount', amounts )
        data.setlist( 'income_handle', handles )
        return data

    def test_a_new_general_line_materializes_with_a_minted_handle( self ):
        profile = self._profile()
        form    = IncomeTableForm( self._post( [ 'Salary' ], [ 'you' ], [ '90,000' ], [ '' ] ),
                                   profile = profile )
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        flow = result.income_flows[ 0 ]
        self.assertEqual( ( flow.name, flow.subject_handle, flow.handle ), ( 'Salary', 'you', 'income-1' ) )
        self.assertEqual( flow.amount, Decimal( '90000' ) )

    def test_an_existing_line_keeps_its_handle( self ):
        existing = IncomeFlow( handle = 'income-1', name = 'Salary', subject_handle = 'you',
                               income_tax_class = IncomeTaxClass.WAGES, amount = Decimal( '90000' ) )
        profile  = self._profile( existing )
        form     = IncomeTableForm( self._post( [ 'Salary' ], [ 'you' ], [ '95,000' ], [ 'income-1' ] ),
                                    profile = profile )
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        self.assertEqual( [ f.handle for f in result.income_flows ], [ 'income-1' ] )
        self.assertEqual( result.income_flows[ 0 ].amount, Decimal( '95000' ) )

    def test_the_household_sentinel_gives_aggregate_income( self ):
        profile = self._profile()
        form    = IncomeTableForm( self._post( [ 'Interest' ], [ '__household__' ], [ '1,000' ], [ '' ] ),
                                   profile = profile )
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        flow = result.income_flows[ 0 ]
        self.assertIsNone( flow.subject_handle )
        self.assertEqual( flow.income_tax_class, IncomeTaxClass.ORDINARY )

    def test_an_incomplete_row_does_not_materialize( self ):
        profile = self._profile()
        form    = IncomeTableForm( self._post( [ 'Salary' ], [ 'you' ], [ '' ], [ '' ] ), profile = profile )
        self.assertTrue( form.is_valid(), form.errors )
        result, _ = form.apply( profile, Plans() )
        self.assertEqual( result.income_flows, [] )

    def test_a_removed_line_drops_the_flow_and_reaps_its_timing( self ):
        existing = IncomeFlow( handle = 'income-1', name = 'Salary', subject_handle = 'you',
                               income_tax_class = IncomeTaxClass.WAGES, amount = Decimal( '90000' ) )
        profile  = self._profile( existing )
        plans    = Plans( income_timing = [ IncomeTiming( flow_handle = 'income-1' ) ] )
        form     = IncomeTableForm( self._post( [], [], [], [] ), profile = profile )   # the row was removed
        self.assertTrue( form.is_valid(), form.errors )
        result, reconciled = form.apply( profile, plans )
        self.assertEqual( result.income_flows, [] )
        self.assertEqual( reconciled.income_timing, [] )

    def test_a_negative_amount_is_a_genuine_error( self ):
        profile = self._profile()
        form    = IncomeTableForm( self._post( [ 'Salary' ], [ 'you' ], [ '-5' ], [ '' ] ), profile = profile )
        self.assertFalse( form.is_valid() )
        self.assertIsNotNone( form.general_rows[ 0 ][ 'error' ] )
