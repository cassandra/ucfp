"""The login-free Social Security claiming calculator pages: the inputs form and the results.

These are public `View`s (no `ensure_organization`, no login) -- the calculator works for an anonymous
visitor or a signed-in one. Inputs are held in the session, NOT the database, so a visit leaves no saved
profile or scenario: the household facts in the neutral `session_facts` slot, the run assumptions in
`ss_timing_assumptions` (see `ucfp.session_state`). The inputs page prefills from the last session entry,
else from a signed-in visitor's Profile and scenario, else the system defaults (see `prefill`).
Submitting persists both and redirects to the results, which runs the sweep.
"""
from decimal import Decimal

from django.http import Http404
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.generic import View

from common import antinode
from common.async_view import ModalView
from common.rate import FULL_RATE, Rate
from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension

from . import methodology, results
from .compute import (
    CLAIM_AGES, COLA_INFLATION_LAG, compare_claiming_strategies, compute_strategy,
    strategy_year_details )
from .forms import BenefitEstimateForm, InputsForm, claimants_and_assumptions, is_runnable
from .prefill import build_prefill

_PERSON_COUNT         = 2
_ESTIMATOR_TEMPLATE   = 'calculators/ss_timing/modals/estimator.html'
_ESTIMATE_FRAGMENT    = 'calculators/ss_timing/modals/benefit_estimate.html'
_PIA_INPUT_TEMPLATE   = 'calculators/ss_timing/modals/pia_input.html'
_DETAIL_TEMPLATE      = 'calculators/ss_timing/_detail.html'
_METHODOLOGY_TEMPLATE = 'calculators/ss_timing/modals/methodology.html'


class InputsView( View ):
    """The public inputs form. GET renders it prefilled from the last session entry (or the default
    assumptions); POST validates, stores the raw inputs in the session, and redirects to the results."""

    template_name = 'calculators/ss_timing/inputs.html'

    def get( self, request ):
        prefill = build_prefill( request )
        form    = InputsForm( initial = prefill.initial )
        return render( request, self.template_name,
                       { 'form' : form, 'from_profile' : prefill.from_profile,
                         'assumptions_source' : prefill.assumptions_source } )

    def post( self, request ):
        form = InputsForm( request.POST )
        if not form.is_valid():
            form.flag_invalid_fields()
            return render( request, self.template_name, { 'form' : form } )
        request.session_state.session_facts         = form.session_facts()
        request.session_state.ss_timing_assumptions = form.assumptions_inputs()
        request.session_state.to_session( request )
        return redirect( 'calculators:ss_timing:results' )


class ResultsView( View ):
    """The public results page: runs the claiming sweep over the stored inputs and renders the heatmap,
    ranked list, and year-by-year detail (with the methodology modal). A visit with no runnable stored
    household (a bookmark, a cleared session) is sent back to the form."""

    template_name = 'calculators/ss_timing/results.html'

    def get( self, request ):
        resolved = _session_claimants_and_assumptions( request )
        if resolved is None:
            return redirect( 'calculators:ss_timing:inputs' )
        claimants, assumptions = resolved
        comparison  = compare_claiming_strategies( claimants, assumptions )
        selected    = comparison.best
        combo       = results.combo_of( selected.claim_ages )
        real_return = Rate( assumptions.discount_rate.fraction - assumptions.inflation.fraction )
        context     = {
            'axis_ages'           : CLAIM_AGES,
            'cola_lag_pct'        : _percent( COLA_INFLATION_LAG ),
            'inflation_pct'       : _percent( assumptions.inflation ),
            'expected_return_pct' : _percent( assumptions.discount_rate ),
            'real_return_pct'     : _percent( real_return ),
            'is_opportunity_cost' : _is_opportunity_cost( assumptions ),
            'payable_pct'         : _percent( assumptions.benefits_payable ),
            'reduction_year'      : assumptions.reduction_year,
            'is_reduced'          : assumptions.benefits_payable != FULL_RATE,
            'heatmap'             : results.heatmap( comparison, combo ),
            'ranked'              : results.ranked( comparison, combo ) }
        context.update( _detail_context(
            comparison.claimants, selected, _is_opportunity_cost( assumptions ) ) )
        return render( request, self.template_name, context )


class StrategyDetailView( View ):
    """The drill-in for one claiming combination -- the antinode target the heatmap and ranked list swap
    into. Recomputes just that strategy (one engine run) rather than the whole sweep, then returns the
    year-by-year detail partial. `combo` is the claim ages joined ('67' or '70-64')."""

    def get( self, request, combo ):
        resolved = _session_claimants_and_assumptions( request )
        if resolved is None:
            raise Http404( 'No calculator inputs in this session.' )
        claimants, assumptions = resolved
        strategy = compute_strategy( claimants, _parse_combo( combo, len( claimants ) ), assumptions )
        content  = render_to_string(
            _DETAIL_TEMPLATE,
            _detail_context( _by_earning( claimants ), strategy, _is_opportunity_cost( assumptions ) ),
            request = request )
        return antinode.response( replace_map = { 'ss-detail' : content } )


class MethodologyModalView( ModalView ):
    """The "how this is calculated" modal for one claiming combination -- the SSA terms and values behind
    the strategy currently shown in the detail. Login-free; reads the stored inputs, not a saved plan."""

    def get_template_name( self ):
        return _METHODOLOGY_TEMPLATE

    def get( self, request, combo ):
        resolved = _session_claimants_and_assumptions( request )
        if resolved is None:
            raise Http404( 'No calculator inputs in this session.' )
        claimants, _assumptions = resolved
        earners    = _by_earning( claimants )
        claim_ages = _parse_combo( combo, len( claimants ) )
        return self.modal_response( request, context = {
            'terms'         : methodology.methodology( earners, claim_ages ),
            'claim_pairs'   : list( zip( earners, claim_ages ) ),
            'reference_url' : methodology.REFERENCE_URL } )


class BenefitEstimatorModalView( ModalView ):
    """The login-free PIA estimator opened beside a person's benefit field. GET renders the modal (a blank
    income and the resulting benefit); POST recomputes the benefit for an adjusted income, swapping just
    that field while the modal stays open. `index` is the person the confirmed estimate writes back to.
    US-only, gated on the jurisdiction having an estimator -- there is no saved profile here, so the income
    is entered in the modal rather than seeded from wages."""

    def get_template_name( self ):
        return _ESTIMATOR_TEMPLATE

    def get( self, request, index ):
        _valid_index( index )
        _pension()
        return self.modal_response(
            request, context = { 'form' : BenefitEstimateForm(), 'index' : index } )

    def post( self, request, index ):
        _valid_index( index )
        pension  = _pension()
        income   = _submitted_amount( request, 'income' )
        form     = BenefitEstimateForm( initial = { 'benefit' : pension.estimate_entitlement( income ) } )
        fragment = render_to_string( _ESTIMATE_FRAGMENT, { 'form' : form }, request = request )
        return antinode.response( replace_map = { 'benefit-estimate' : fragment } )


class BenefitEstimateApplyView( View ):
    """Confirm handler: write the estimated benefit into the calculator's PIA field for `index`. There is
    no profile to persist to, so it re-renders that one input with the value and swaps it in place; the
    confirm form carries no `data-stay-in-modal`, so antinode also closes the modal."""

    def post( self, request, index ):
        _valid_index( index )
        benefit = _submitted_amount( request, 'benefit' )
        field   = InputsForm( initial = { f's{index}_pia' : str( benefit ) } )[ f's{index}_pia' ]
        content = render_to_string( _PIA_INPUT_TEMPLATE, { 'field' : field }, request = request )
        return antinode.response( replace_map = { f'pia-input-{index}' : content } )


def _session_claimants_and_assumptions( request ):
    """The compute core's claimants and assumptions from this session's stored slots, or None when the
    session does not hold a runnable household -- no entry yet, or a partial/oversized one left by another
    tool sharing `SessionFacts`. The single gate the results, drill-in, and methodology views share to send
    such a visit back to the form rather than erroring mid-compute."""
    facts       = request.session_state.session_facts
    assumptions = request.session_state.ss_timing_assumptions
    if not is_runnable( facts, assumptions ):
        return None
    return claimants_and_assumptions( facts, assumptions )


def _pension() -> GovernmentPension:
    """The US government-pension facade, or a 404 where the jurisdiction has no benefit estimator -- the
    same gate the opener applies, so the endpoint never returns a bad estimate."""
    pension = GovernmentPension( JurisdictionType.US_FEDERAL )
    if not pension.has_benefit_estimator():
        raise Http404( 'This jurisdiction has no Social Security benefit estimator.' )
    return pension


def _valid_index( index : int ) -> None:
    """Guard the person index -- the calculator models at most two people, so only 0 and 1 are valid."""
    if index not in range( _PERSON_COUNT ):
        raise Http404( f'No person {index} on the calculator.' )


def _submitted_amount( request, field : str ) -> Decimal:
    """The posted `field` money value parsed through the estimator form -- a blank or unparseable value
    falls back to zero, so a mid-interaction recompute or confirm always yields a figure rather than
    erroring."""
    form  = BenefitEstimateForm( request.POST )
    value = form.cleaned_data.get( field ) if form.is_valid() else None
    return value if value is not None else Decimal( '0' )


def _detail_context( earners, strategy, is_opportunity_cost ) -> dict:
    """The year-by-year detail table's context for `strategy` -- the earners (higher first) for the column
    labels, the per-year rows apportioned into own/spousal/survivor, and `is_opportunity_cost` so the table
    shows the effective-value column (it renders standalone on drill-in, so it carries the flag itself)."""
    return {
        'earners'             : earners,
        'is_couple'           : len( earners ) == 2,
        'is_opportunity_cost' : is_opportunity_cost,
        'strategy'            : strategy,
        'combo'               : results.combo_of( strategy.claim_ages ),
        'claim_pairs'         : list( zip( earners, strategy.claim_ages ) ),
        'rows'                : strategy_year_details( tuple( earners ), strategy ) }


def _is_opportunity_cost( assumptions ) -> bool:
    """Whether present value and effective value differ -- the expected return is set above inflation, so
    the discount prices in an opportunity cost. False recovers the plain today's-dollars view."""
    return assumptions.discount_rate != assumptions.inflation


def _by_earning( claimants ):
    """Claimants ordered higher earner first (by PIA) -- the order the detail columns read."""
    return tuple( sorted( claimants, key = lambda claimant: claimant.pia_monthly, reverse = True ) )


def _percent( rate ) -> str:
    """A Rate as a trimmed percent string for the assumptions chips -- Rate(0.025) -> '2.5%',
    Rate(1) -> '100%'. Fixed-point format so a whole percent does not render in scientific notation."""
    value = ( rate.fraction * Decimal( '100' ) ).normalize()
    return f'{ format( value, "f" ) }%'


def _parse_combo( combo : str, count : int ) -> tuple[ int, ... ]:
    """The claim ages from a URL combo key ('67' or '70-64'), validated against the household size and the
    62..70 range -- a bad key is a 404 rather than a mis-drawn table."""
    try:
        ages = tuple( int( part ) for part in combo.split( '-' ) )
    except ValueError:
        raise Http404( f'Bad claim-age combo {combo!r}.' )
    if len( ages ) != count or any( age not in CLAIM_AGES for age in ages ):
        raise Http404( f'Claim-age combo {combo!r} does not match the household.' )
    return ages
