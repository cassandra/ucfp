"""The login-free Social Security claiming calculator pages: the inputs form and the results.

These are public `View`s (no `ensure_organization`, no login) -- the calculator works for an anonymous
visitor or a signed-in one. Inputs are held in the session (`ss_timing_inputs`), NOT the database, so a
visit leaves no saved profile or scenario. The inputs page prefills from the last session entry, else
from a signed-in visitor's Profile and scenario, else the system defaults (see `ss_timing_prefill`).
Submitting persists the inputs and redirects to the results, which runs the sweep.
"""
from django.shortcuts import redirect, render
from django.views.generic import View

from .ss_timing import compare_claiming_strategies
from .ss_timing_forms import SocialSecurityTimingForm, claimants_and_assumptions
from .ss_timing_prefill import build_prefill


class SocialSecurityTimingInputsView( View ):
    """The public inputs form. GET renders it prefilled from the last session entry (or the default
    assumptions); POST validates, stores the raw inputs in the session, and redirects to the results."""

    template_name = 'planning/ss_timing/inputs.html'

    def get( self, request ):
        remembered = request.session_state.ss_timing_inputs
        if remembered:
            form = SocialSecurityTimingForm( initial = remembered )
            return render( request, self.template_name, { 'form' : form, 'remembered' : True } )
        prefill = build_prefill( request )
        form    = SocialSecurityTimingForm( initial = prefill.initial )
        return render( request, self.template_name,
                       { 'form' : form, 'from_profile' : prefill.from_profile,
                         'assumptions_source' : prefill.assumptions_source } )

    def post( self, request ):
        form = SocialSecurityTimingForm( request.POST )
        if not form.is_valid():
            return render( request, self.template_name, { 'form' : form } )
        request.session_state.ss_timing_inputs = form.cleaned_inputs()
        request.session_state.to_session( request )
        return redirect( 'ss_timing_results' )


class SocialSecurityTimingResultsView( View ):
    """The public results page: runs the claiming sweep over the stored inputs and shows the ranking. A
    visit with no stored inputs (a bookmark, a cleared session) is sent back to the form. Phase 5 replaces
    the minimal rendering here with the heatmap, ranked list, year detail, and methodology modal."""

    template_name = 'planning/ss_timing/results.html'

    def get( self, request ):
        inputs = request.session_state.ss_timing_inputs
        if not inputs:
            return redirect( 'ss_timing' )
        claimants, assumptions = claimants_and_assumptions( inputs )
        comparison = compare_claiming_strategies( claimants, assumptions )
        best       = comparison.best
        return render( request, self.template_name,
                       { 'comparison' : comparison, 'best' : best,
                         'claimants' : comparison.claimants,
                         'best_pairs' : list( zip( comparison.claimants, best.claim_ages ) ) } )
