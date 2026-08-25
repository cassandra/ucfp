"""The Debts section as a list of summaries, each opened in its own editor card (mirroring Vehicles).
`DebtForm` writes one debt; `debts_context` builds the list (editable loans/cards vs read-only
mortgages/autos); `delete_debt` removes one and leaves Plans as drift (reconciled on demand, not eagerly
reaped)."""
from decimal import Decimal

from django.http import QueryDict
from django.test import SimpleTestCase
from django.urls import reverse

from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.inputs.debts import (
    DebtForm, _minted_debt_handle, debt_heading, debts_context, delete_debt )
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt, LoanTerms, Profile
from ucfp.inputs.plans.schemas import LoanRepayment, Plans


def _apply( profile, handle = None, **fields ):
    data = QueryDict( mutable = True )
    data.update( fields )
    form = DebtForm( data, profile = profile, plans = Plans(), handle = handle )
    assert form.is_valid(), form.errors
    return form.apply( profile, Plans() )


def _student( handle = 'debt-1', name = 'Student loan', terms = None ) -> Debt:
    return Debt( handle = handle, name = name, kind = DebtKind.STUDENT, balance = Decimal( '15000' ),
                 terms = terms )


def _mortgage() -> Debt:
    return Debt( handle = 'residence-mortgage', name = 'Mortgage', kind = DebtKind.MORTGAGE,
                 balance = Decimal( '200000' ), secured_asset = 'residence' )


def _auto() -> Debt:
    return Debt( handle = 'vehicle-1-loan', name = 'Civic loan', kind = DebtKind.AUTO,
                 balance = Decimal( '18000' ), secured_asset = 'vehicle-1' )


class DebtFormWriteTests( SimpleTestCase ):

    def test_a_new_amortizing_debt_stores_its_terms( self ):
        profile, _ = _apply( Profile(), handle = 'debt-1', kind = 'STUDENT', name = 'Student loan',
                             balance = '15000', loan_payment = '450', loan_term = '48' )
        debt = profile.debts[ 0 ]
        self.assertEqual( ( debt.handle, debt.kind ), ( 'debt-1', DebtKind.STUDENT ) )
        self.assertEqual( debt.terms.remaining_term.months(), 48 )
        self.assertGreater( debt.terms.interest_rate.fraction, Decimal( '0' ) )   # back-solved

    def test_a_credit_card_stores_no_terms( self ):
        profile, _ = _apply( Profile(), handle = 'debt-1', kind = 'CREDIT_CARD', name = 'Visa',
                             balance = '3000', loan_payment = '200', loan_term = '24' )
        self.assertIsNone( profile.debts[ 0 ].terms )

    def test_a_partial_debt_writes_nothing( self ):
        profile, _ = _apply( Profile(), handle = 'debt-1', kind = 'STUDENT', name = '', balance = '15000' )
        self.assertEqual( profile.debts, [] )

    def test_a_new_debt_without_a_handle_mints_one( self ):
        profile, _ = _apply( Profile(), kind = 'PERSONAL', name = 'Personal loan', balance = '5000' )
        self.assertEqual( profile.debts[ 0 ].handle, 'debt-1' )

    def test_editing_upserts_by_handle_leaving_other_debts_intact( self ):
        profile = Profile( debts = [ _student( 'debt-1' ),
                                     Debt( handle = 'debt-2', name = 'Personal', kind = DebtKind.PERSONAL,
                                           balance = Decimal( '5000' ) ) ] )
        profile, _ = _apply( profile, handle = 'debt-1', kind = 'STUDENT', name = 'Renamed',
                             balance = '12000' )
        by_handle = { d.handle: d for d in profile.debts }
        self.assertEqual( by_handle[ 'debt-1' ].name, 'Renamed' )
        self.assertEqual( by_handle[ 'debt-1' ].balance, Decimal( '12000' ) )
        self.assertEqual( by_handle[ 'debt-2' ].name, 'Personal' )               # untouched

    def test_the_editor_pre_fills_from_stored_facts( self ):
        terms   = LoanTerms( interest_rate = Rate.percent( 6 ),
                             remaining_term = Duration( 48, TimeUnit.MONTH ),
                             monthly_payment = Decimal( '450' ) )
        profile = Profile( debts = [ _student( 'debt-1', terms = terms ) ] )
        form    = DebtForm( profile = profile, plans = Plans(), handle = 'debt-1' )
        self.assertEqual( form.initial[ 'kind' ], 'STUDENT' )
        self.assertEqual( form.initial[ 'balance' ], Decimal( '15000' ) )
        self.assertEqual( form.initial[ 'loan_rate' ], Decimal( '6' ) )
        self.assertEqual( form.initial[ 'loan_term' ], 48 )

    def test_neither_mortgage_nor_auto_is_an_addable_kind( self ):
        kinds = { name for name, _label in DebtForm._KIND_CHOICES }
        self.assertNotIn( DebtKind.MORTGAGE.name, kinds )
        self.assertNotIn( DebtKind.AUTO.name, kinds )

    def test_apply_refuses_to_rewrite_a_canonical_elsewhere_debt( self ):
        # The debt/<handle>/ route is a catch-all, so a crafted post could name a mortgage/auto handle with
        # an editable kind; apply must leave it untouched (edited only in its canonical section).
        profile   = Profile( debts = [ _mortgage() ] )
        result, _ = _apply( profile, handle = 'residence-mortgage', kind = 'STUDENT', name = 'Sneaky',
                            balance = '1000' )
        debt = result.debts[ 0 ]
        self.assertEqual( ( debt.handle, debt.kind, debt.name ),
                          ( 'residence-mortgage', DebtKind.MORTGAGE, 'Mortgage' ) )   # unchanged


class DebtsContextTests( SimpleTestCase ):
    """The list distinguishes editable loans/cards from read-only mortgages/autos (a pointer to their
    section), and summarizes captured terms."""

    def test_editable_and_read_only_rows_are_flagged( self ):
        profile = Profile( debts = [ _mortgage(), _auto(), _student() ] )
        rows    = { row[ 'name' ]: row for row in debts_context( profile ) }
        self.assertFalse( rows[ 'Mortgage' ][ 'editable' ] )
        self.assertEqual( rows[ 'Mortgage' ][ 'source_note' ], 'From Home' )       # secured on the residence
        self.assertEqual( rows[ 'Civic loan' ][ 'source_note' ], 'From Vehicles' )
        self.assertTrue( rows[ 'Student loan' ][ 'editable' ] )
        self.assertIsNone( rows[ 'Student loan' ][ 'source_note' ] )

    def test_a_mortgage_on_another_property_points_to_other_property( self ):
        # The old single "Home & Property" section split into Home (the residence) and Other property; a
        # mortgage on a non-residence property points to the latter, keyed off its secured asset.
        rental_mortgage = Debt( handle = 'rental-mortgage', name = 'Rental mortgage',
                                kind = DebtKind.MORTGAGE, balance = Decimal( '150000' ),
                                secured_asset = 'property-1' )
        rows = { row[ 'name' ]: row for row in debts_context( Profile( debts = [ rental_mortgage ] ) ) }
        self.assertEqual( rows[ 'Rental mortgage' ][ 'source_note' ], 'From Other property' )

    def test_a_row_summarizes_captured_terms( self ):
        terms   = LoanTerms( interest_rate = Rate.percent( 4 ),
                             remaining_term = Duration( 240, TimeUnit.MONTH ),
                             monthly_payment = Decimal( '1800' ) )
        profile = Profile( debts = [ _student( terms = terms ) ] )
        self.assertEqual( debts_context( profile )[ 0 ][ 'terms' ], '4% · 240 mo · $1,800/mo' )

    def test_an_editable_row_carries_its_action_urls_a_read_only_row_none( self ):
        # The item card's Edit/Remove post to these; a read-only mortgage/auto has no editor here.
        profile = Profile( debts = [ _student(), _mortgage() ] )
        rows    = { row[ 'name' ]: row for row in debts_context( profile ) }
        self.assertEqual( rows[ 'Student loan' ][ 'edit_url' ],
                          reverse( 'debt_edit', kwargs = { 'handle': 'debt-1' } ) )
        self.assertEqual( rows[ 'Student loan' ][ 'delete_url' ],
                          reverse( 'debt_delete', kwargs = { 'handle': 'debt-1' } ) )
        self.assertIsNone( rows[ 'Mortgage' ][ 'edit_url' ] )
        self.assertIsNone( rows[ 'Mortgage' ][ 'delete_url' ] )


class DebtHeadingAndDeleteTests( SimpleTestCase ):

    def test_heading_names_a_saved_debt_and_is_none_for_an_unsaved_handle( self ):
        profile = Profile( debts = [ _student( 'debt-1' ) ] )
        self.assertEqual( debt_heading( profile, 'debt-1' ),
                          { 'handle': 'debt-1', 'name': 'Student loan', 'kind': 'Student loan' } )
        self.assertIsNone( debt_heading( profile, 'debt-9' ) )

    def test_delete_removes_the_debt( self ):
        profile   = Profile( debts = [ _student( 'debt-1' ) ] )
        result, _ = delete_debt( profile, Plans(), 'debt-1' )
        self.assertEqual( result.debts, [] )

    def test_delete_leaves_the_repayment_plan_as_drift( self ):
        profile = Profile( debts = [ _student( 'debt-1' ) ] )
        plans   = Plans( loan_repayments = [ LoanRepayment(
            debt_handle = 'debt-1', interest_rate = Rate( Decimal( '0.04' ) ),
            remaining_term = Duration( 25, TimeUnit.YEAR ) ) ] )
        _, reconciled = delete_debt( profile, plans, 'debt-1' )
        self.assertEqual( [ r.debt_handle for r in reconciled.loan_repayments ], [ 'debt-1' ] )


class MintHandleTests( SimpleTestCase ):

    def test_it_mints_the_lowest_free_handle_across_all_debts( self ):
        profile = Profile( debts = [ _student( 'debt-1' ), _auto() ] )   # includes a read-only auto loan
        self.assertEqual( _minted_debt_handle( profile ), 'debt-2' )
