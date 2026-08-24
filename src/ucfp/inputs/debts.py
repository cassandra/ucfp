"""§ Debts: the household's debts as a list of summaries, each opened in its own editor card.

Every debt is listed, but the editor scope differs by kind, so each loan has exactly one editor:

- **Unsecured amortizing loans** (student / personal / other) and **credit cards** are editable here -- a
  kind, a name, the current balance, and (for an amortizing loan) its contract terms (rate / term /
  payment) entered through the shared loan-terms block. A card carries no terms.
- **Mortgages and auto loans** are read-only here, shown with a pointer to their canonical section (Home &
  Property for a mortgage, Vehicles for an auto loan), where their balance and terms are entered.

This one-editor-per-loan rule also fixes the former two-writer bug (a mortgage was editable both here and
on its property). The list (`debts_context`) offers Edit/Remove only on the editable debts; the editor
(`DebtForm`) writes one debt, keyed by its stable `handle` so Plans references survive an edit.
"""
from dataclasses import replace

from django import forms

from common.forms import CHOOSE_PLACEHOLDER, MoneyField

from ucfp.environment.constants import AppConst
from ucfp.inputs.loan_fieldset import LoanTermsFieldsMixin, loan_terms_initial
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt


_HANDLE_PREFIX = 'debt-'

# Debts whose canonical editor is another section: listed read-only here with a pointer to it, never
# edited or deleted here. A mortgage is entered on its property; an auto loan on its vehicle.
_CANONICAL_ELSEWHERE = {
    DebtKind.MORTGAGE : 'Home & Property',
    DebtKind.AUTO     : 'Vehicles',
}

# The kind values whose editor reveals the loan-terms block -- the amortizing loans editable here
# (student / personal / other); a credit card is editable but carries no terms.
_AMORTIZING_CASE_VALUES = ' '.join(
    kind.name for kind in DebtKind if kind.is_amortizing and kind not in _CANONICAL_ELSEWHERE )


def _minted_debt_handle( profile ) -> str:
    """The lowest `debt-N` handle free among every current debt -- a stable identity a new debt keeps
    across edits, since Plans reference debts by handle."""
    taken = { debt.handle for debt in profile.debts } if profile is not None else set()
    index = 1
    while f'{_HANDLE_PREFIX}{index}' in taken:
        index += 1
    return f'{_HANDLE_PREFIX}{index}'


def _terms_summary( terms ) -> str:
    """A read-only one-line summary of a debt's contract terms, or empty when none are captured -- e.g.
    `4% · 240 mo · $1,800/mo`."""
    if terms is None:
        return ''
    parts = []
    if terms.interest_rate is not None:
        percent = terms.interest_rate.fraction * 100
        parts.append( f'{percent:.2f}'.rstrip( '0' ).rstrip( '.' ) + '%' )
    if terms.remaining_term is not None:
        parts.append( f'{terms.remaining_term.months()} mo' )
    if terms.monthly_payment is not None:
        parts.append( f'${terms.monthly_payment:,.0f}/mo' )
    return ' · '.join( parts )


def debts_context( profile ) -> list:
    """One summary row per debt for the list -- editable debts (unsecured loans, cards) carry an editor,
    read-only mortgages/autos a pointer to their section. Each: handle, name, kind label, balance, a terms
    summary, `editable`, and (read-only only) `managed_in`."""
    return [ { 'handle'     : debt.handle,
               'name'       : debt.name,
               'kind'       : debt.kind.label,
               'balance'    : debt.balance,
               'terms'      : _terms_summary( debt.terms ),
               'editable'   : debt.kind not in _CANONICAL_ELSEWHERE,
               'managed_in' : _CANONICAL_ELSEWHERE.get( debt.kind ) }
             for debt in ( profile.debts if profile is not None else [] ) ]


def debt_heading( profile, handle : str ):
    """The {handle, name, kind} of a saved debt for the editor card header, or None when the handle names
    no saved debt yet (a just-added one being filled in)."""
    debt = next( ( d for d in ( profile.debts if profile is not None else [] ) if d.handle == handle ),
                 None )
    return { 'handle' : handle, 'name' : debt.name, 'kind' : debt.kind.label } if debt is not None else None


def delete_debt( profile, plans, handle : str ):
    """Remove a debt. Plans are untouched: a repayment left keyed to the removed debt is reconciled on
    demand at the run surface, not dropped here."""
    return replace( profile, debts = [ d for d in profile.debts if d.handle != handle ] ), plans


class DebtForm( LoanTermsFieldsMixin, forms.Form ):
    """The add/edit editor for one debt -- a kind, a name, the current balance, and (for an amortizing
    loan, revealed by the kind switch) the shared loan-terms block. Only the editable kinds (unsecured
    loans and cards) are offered; mortgages and auto loans are entered in their canonical section. Keyed by
    `handle`; non-blocking and background-saved -- a partial debt (missing a kind, name, or balance) simply
    is not written, and other debts are left intact."""

    # The editor holds a single loan block, so a fixed hint id is unambiguous.
    LOAN_HINT_ID = 'debt-loan-hint'

    # Addable/editable kinds: unsecured amortizing loans and cards. Mortgages and autos are entered in
    # their canonical section (read-only in the list), so they are not offered.
    _KIND_CHOICES = ( ( '', CHOOSE_PLACEHOLDER ), ) + tuple(
        ( kind.name, kind.label ) for kind in DebtKind if kind not in _CANONICAL_ELSEWHERE )

    kind    = forms.ChoiceField(
        label = 'Type', required = False, choices = _KIND_CHOICES,
        widget = forms.Select( attrs = { 'class' : f'custom-select {AppConst.SWITCH_CONTROL_CLASS}' } ) )
    name    = forms.CharField(
        label = 'Name', max_length = 100, required = False,
        widget = forms.TextInput( attrs = { 'class' : 'form-control' } ) )
    balance = MoneyField(
        label = 'Balance owed', min_value = 0, required = False,
        css_class = AppConst.LOAN_BALANCE_CLASS )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        self._profile = profile
        self._handle  = handle
        super().__init__( data, initial = self._initial( profile, handle ) if handle else None )

    @staticmethod
    def _initial( profile, handle : str ) -> dict:
        debt = next( ( d for d in ( profile.debts if profile is not None else [] ) if d.handle == handle ),
                     None )
        if debt is None or debt.kind in _CANONICAL_ELSEWHERE:
            return dict()                              # a fresh editor (or a kind not editable here)
        initial = { 'kind' : debt.kind.name, 'name' : debt.name, 'balance' : debt.balance }
        initial.update( loan_terms_initial( debt.terms ) )
        return initial

    @property
    def amortizing_cases( self ) -> str:
        """The kind values whose editor reveals the loan-terms block -- the switch-case the template
        marks that block with."""
        return _AMORTIZING_CASE_VALUES

    def _complete( self ) -> bool:
        """The fields a debt needs to materialize are present -- a kind, a name, and a balance. No hard
        validation: a partial debt is simply not written rather than fighting a background save."""
        cleaned = self.cleaned_data
        return bool( cleaned.get( 'kind' ) ) and bool( cleaned.get( 'name' ) ) \
            and cleaned.get( 'balance' ) is not None

    def apply( self, profile, plans ):
        # Non-blocking and non-destructive: a partial edit writes nothing and leaves other debts intact. A
        # complete form upserts this one debt by handle, preserving any secured link (unsecured debts carry
        # none). Plans are never adjusted here -- a repayment stranded by a removed debt is reconciled on
        # demand at the run surface.
        if not self._complete():
            return profile, plans
        handle   = self._handle or _minted_debt_handle( profile )
        kind     = DebtKind[ self.cleaned_data[ 'kind' ] ]
        balance  = self.cleaned_data[ 'balance' ]
        existing = next( ( d for d in profile.debts if d.handle == handle ), None )
        debt = Debt(
            handle = handle, name = self.cleaned_data[ 'name' ], kind = kind, balance = balance,
            secured_asset = existing.secured_asset if existing is not None else None,
            terms = self.loan_terms( balance ) if kind.is_amortizing else None )
        debts = [ d for d in profile.debts if d.handle != handle ] + [ debt ]
        return replace( profile, debts = debts ), plans
