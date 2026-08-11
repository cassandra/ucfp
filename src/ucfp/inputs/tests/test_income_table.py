"""The income facts pane can re-render its edits: its wrapper carries the antinode swap-target id.

`IncomeTableView` is a `SelfSavingPaneView`, so a save that adds or removes a line re-renders the pane via
antinode's `replace_map` keyed on `IncomeTableView.target`. That swap only lands if the rendered pane
carries a matching `id`. Without it, edits persist but the table never re-renders -- a filled blank row
does not spawn a fresh one, and a remove checkbox does nothing until a full page reload. This pins the
pane's wrapper id to the view's declared target so the two cannot drift apart again.
"""
from datetime import date

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from ucfp.environment.constants import AppConst
from ucfp.inputs.income import IncomeTableForm
from ucfp.inputs.profile.schemas import Profile, SubjectProfile
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
