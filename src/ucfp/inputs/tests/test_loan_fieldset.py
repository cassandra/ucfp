"""Tests for the shared loan-terms fieldset -- `solved_loan_terms` (turning the user's entries into a
consistent `LoanTerms`) and the field factories, plus that a `Debt` carrying terms round-trips through the
JSON persistence layer."""
from decimal import Decimal

from django.test import SimpleTestCase

from common.dataclass_json import from_json_data, to_json_data
from common.loan_solver import monthly_payment
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.environment.constants import AppConst
from ucfp.inputs.loan_fieldset import (
    loan_payment_field, loan_rate_field, loan_term_field, solved_loan_terms )
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt, LoanTerms


def _months( count : int ) -> Duration:
    return Duration( count, TimeUnit.MONTH )


class SolvedLoanTermsTest( SimpleTestCase ):
    """The solver builds a consistent `LoanTerms`: the rate is taken as entered or back-solved from the
    payment; the payment is re-derived from balance + rate + term so the stored trio agrees."""

    def test_rate_and_term_derive_a_consistent_payment( self ):
        terms = solved_loan_terms( Decimal( '20000' ), Rate.percent( 6 ), _months( 36 ), None )
        expected = Decimal( round( monthly_payment( Decimal( '20000' ), Rate.percent( 6 ), 36 ) ) )
        self.assertEqual( terms.interest_rate, Rate.percent( 6 ) )
        self.assertEqual( terms.remaining_term, _months( 36 ) )
        self.assertEqual( terms.monthly_payment, expected )

    def test_payment_and_term_back_solve_the_rate( self ):
        # The number people know -- payment + months + balance -- yields the rate they don't.
        payment = Decimal( round( monthly_payment( Decimal( '20000' ), Rate.percent( 5 ), 36 ) ) )
        terms   = solved_loan_terms( Decimal( '20000' ), None, _months( 36 ), payment )
        self.assertEqual( round( terms.interest_rate.fraction, 3 ), Decimal( '0.050' ) )
        self.assertEqual( terms.remaining_term, _months( 36 ) )

    def test_an_entered_rate_wins_over_an_entered_payment( self ):
        # Over-determined: the rate is authoritative, so the payment is re-derived from it (not kept).
        terms    = solved_loan_terms( Decimal( '20000' ), Rate.percent( 6 ), _months( 36 ), Decimal( '999' ) )
        expected = Decimal( round( monthly_payment( Decimal( '20000' ), Rate.percent( 6 ), 36 ) ) )
        self.assertEqual( terms.interest_rate, Rate.percent( 6 ) )
        self.assertEqual( terms.monthly_payment, expected )

    def test_an_implausible_payment_stores_no_rate( self ):
        # ~60% APR: the payment doesn't form a real loan, so no rate is fabricated (payment kept as-is).
        high  = Decimal( round( monthly_payment( Decimal( '20000' ), Rate.percent( 60 ), 36 ) ) )
        terms = solved_loan_terms( Decimal( '20000' ), None, _months( 36 ), high )
        self.assertIsNone( terms.interest_rate )
        self.assertEqual( terms.monthly_payment, high )

    def test_a_partial_entry_stores_what_is_given( self ):
        # Rate only, no term: nothing to derive, but the rate is a legitimate captured fact.
        terms = solved_loan_terms( Decimal( '20000' ), Rate.percent( 6 ), None, None )
        self.assertEqual( terms.interest_rate, Rate.percent( 6 ) )
        self.assertIsNone( terms.remaining_term )
        self.assertIsNone( terms.monthly_payment )

    def test_nothing_entered_is_none( self ):
        # A balance-only loan -- no terms captured at all.
        self.assertIsNone( solved_loan_terms( Decimal( '20000' ), None, None, None ) )


class LoanFieldFactoryTest( SimpleTestCase ):
    """The factories tag each field with the shared `LOAN_*` class the client solver binds to, and wire the
    rate's `aria-describedby` to the block hint."""

    def test_each_field_carries_its_shared_class( self ):
        self.assertIn( AppConst.LOAN_RATE_CLASS, loan_rate_field().widget.attrs[ 'class' ] )
        self.assertIn( AppConst.LOAN_TERM_CLASS, loan_term_field().widget.attrs[ 'class' ] )
        self.assertIn( AppConst.LOAN_PAYMENT_CLASS, loan_payment_field().widget.attrs[ 'class' ] )

    def test_the_rate_points_at_the_named_hint( self ):
        field = loan_rate_field( hint_id = 'current-loan-hint' )
        self.assertEqual( field.widget.attrs[ 'aria-describedby' ], 'current-loan-hint' )


class DebtTermsRoundTripTest( SimpleTestCase ):
    """A `Debt` with contract terms survives the JSON persistence round-trip -- the new optional field and
    its nested `Rate`/`Duration` restore unchanged, and a balance-only debt still restores with no terms."""

    def test_a_debt_with_terms_round_trips( self ):
        debt = Debt(
            handle = 'debt-1', name = 'Car', kind = DebtKind.AUTO, balance = Decimal( '18000' ),
            terms = LoanTerms( interest_rate = Rate.percent( 5 ), remaining_term = _months( 36 ),
                               monthly_payment = Decimal( '540' ) ) )
        self.assertEqual( from_json_data( Debt, to_json_data( debt ) ), debt )

    def test_a_balance_only_debt_round_trips_with_no_terms( self ):
        debt = Debt( handle = 'debt-2', name = 'Loan', kind = DebtKind.PERSONAL, balance = Decimal( '5000' ) )
        restored = from_json_data( Debt, to_json_data( debt ) )
        self.assertEqual( restored, debt )
        self.assertIsNone( restored.terms )
