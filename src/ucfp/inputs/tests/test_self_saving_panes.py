"""The self-saving pane base contract: every interview pane can render and swap itself.

`SelfSavingPaneView.get`/`post` call `self._pane` and `self._swap`, so those must resolve on every pane.
A regression guard: they once slipped into a mixin, which left the panes that do not use the mixin
raising `AttributeError` on GET -- invisible to the form-level unit tests. These pin the view layer.
"""
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase

from organization.models import Organization

from ucfp.inputs.views import SelfSavingPaneView, TransactionCostsView
from ucfp.session_state import SessionState


def _pane_views() -> list:
    """Every concrete `SelfSavingPaneView` subclass."""
    views, seen = list(), set()
    stack = list( SelfSavingPaneView.__subclasses__() )
    while stack:
        view = stack.pop()
        if view in seen:
            continue
        seen.add( view )
        views.append( view )
        stack.extend( view.__subclasses__() )
    return views


class SelfSavingPaneContractTest( SimpleTestCase ):

    def test_every_pane_resolves_the_render_and_swap_methods( self ):
        # `_pane`/`_swap` (used by get/post) and `totals_fragments` must resolve on every pane, whether
        # or not it mixes in totals -- else a pane without the mixin breaks on GET.
        for view in _pane_views():
            self.assertTrue( hasattr( view, '_pane' ), view.__name__ )
            self.assertTrue( hasattr( view, '_swap' ), view.__name__ )
            self.assertTrue( hasattr( view, 'totals_fragments' ), view.__name__ )


class NonTotalsPaneRendersTest( TestCase ):
    """A pane that does not show totals still renders on GET -- exercising the base `_pane` path that the
    mixin-placement regression broke. (The totals panes' GET/render is covered by their own tests.)"""

    def setUp( self ):
        call_command( 'seed_parameter_sets' )        # default assumptions load the seeded economic outlook
        self.organization = Organization.objects.create( name = 'Org' )

    def test_a_non_totals_pane_renders_on_get( self ):
        request = RequestFactory().get( '/inputs/interview/transaction-costs/edit/' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        response = TransactionCostsView().get( request )
        self.assertEqual( response.status_code, 200 )
