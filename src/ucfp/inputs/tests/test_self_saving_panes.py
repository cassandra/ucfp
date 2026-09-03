"""The self-saving pane base contract: every interview pane can render and swap itself.

`SelfSavingPaneView.get`/`post` call `self._pane` and `self._swap`, so those must resolve on every pane.
A regression guard: they once slipped into a mixin, which left the panes that do not use the mixin
raising `AttributeError` on GET -- invisible to the form-level unit tests. These pin the view layer.
"""
from decimal import Decimal

from django.test import RequestFactory, SimpleTestCase, TestCase

from common.rate import Rate
from organization.models import Organization

from ucfp.inputs.assumptions.repository import load_assumptions
from ucfp.inputs.views import (
    AdvancedEconomicsView, SelfSavingPaneView, SocialSecurityFundingView, TransactionCostsView,
    current_assumptions_record )
from ucfp.parameter_sets.management.seeding import seed_default_parameter_sets
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
        seed_default_parameter_sets()        # default assumptions load the seeded economic outlook
        self.organization = Organization.objects.create( name = 'Org' )

    def test_a_non_totals_pane_renders_on_get( self ):
        request = RequestFactory().get( '/inputs/interview/transaction-costs/edit/' )
        request.organization  = self.organization
        request.session_state = SessionState()
        request.session       = dict()
        response = TransactionCostsView().get( request )
        self.assertEqual( response.status_code, 200 )


class SharedEconomicsObjectPersistenceTest( TestCase ):
    """The reorg made three Advanced/Economics panes edit the SAME economics value-object (the main rates,
    the niche rates, and the SS-funding share). Each does an independent load-modify-save of the whole
    Assumptions record, so one pane's save must preserve the fields the other panes own -- the
    compose-without-clobbering invariant, exercised here through the real view + persistence seam rather
    than at the `form.apply` level."""

    _NICHE_POST   = {
        'bond_appreciation': '5', 'precious_metals_appreciation': '0',
        'collectibles_appreciation': '0', 'depreciation_rate': '0', 'rental_increase': '0' }
    _FUNDING_POST = { 'social_security_benefits_payable': '80', 'social_security_reduction_year': '2032' }

    def setUp( self ):
        seed_default_parameter_sets()        # a minted Assumptions loads the seeded Expected outlook
        self.organization  = Organization.objects.create( name = 'Org' )
        self.session_state = SessionState()

    def _request( self, method_request ):
        method_request.organization  = self.organization
        method_request.session_state = self.session_state
        method_request.session       = dict()
        return method_request

    def _save( self, view, data ):
        response = view().post( self._request( RequestFactory().post( '/', data ) ) )
        self.assertEqual( response.status_code, 200 )   # a silent save, not a re-render on error

    def test_saving_one_economics_pane_preserves_the_fields_owned_by_the_others( self ):
        self._save( AdvancedEconomicsView, self._NICHE_POST )        # writes a niche rate
        self._save( SocialSecurityFundingView, self._FUNDING_POST )  # then the funding share
        record    = current_assumptions_record( self._request( RequestFactory().get( '/' ) ) )
        economics = load_assumptions( record ).economics
        # the niche edit survived the later funding save, the funding edit persisted, and a main-pane rate
        # (the Expected-preset inflation) was left untouched by both Advanced saves.
        self.assertEqual( economics.bond_appreciation, Rate.percent( Decimal( '5' ) ) )
        self.assertEqual( economics.social_security_benefits_payable, Rate.percent( Decimal( '80' ) ) )
        self.assertEqual( economics.inflation, Rate.percent( Decimal( '3' ) ) )
