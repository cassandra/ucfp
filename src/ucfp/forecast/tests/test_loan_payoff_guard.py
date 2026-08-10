"""A scheduled loan payoff of a loan account that never materialized is a safe no-op (#151 Phase 2, which
closes #150): selling a financed vehicle whose loan has no terms -- or any payoff of an absent loan -- must
not fail the run. A handle that resolves to a non-liability is still a real wiring error.
"""
from datetime import date

from django.test import SimpleTestCase

from ucfp.accounts.books import Account, BooksOfAccount
from ucfp.accounts.chart import Chart
from ucfp.accounts.enums import AccountType
from ucfp.accounts.exceptions import MissingAccountError
from ucfp.forecast.parameters import ScheduledLoanPayoff


class LoanPayoffGuardTests( SimpleTestCase ):

    def _chart( self, *accounts ):
        return Chart( BooksOfAccount( accounts = list( accounts ) ) )

    def test_a_payoff_of_a_missing_loan_account_is_skipped( self ):
        payoff = ScheduledLoanPayoff( event_date = date( 2030, 1, 1 ), loan = 'vehicle-loan:vehicle-9' )
        self.assertIsNone( payoff.to_period_event( {}, self._chart() ) )      # nothing to extinguish

    def test_a_payoff_targeting_a_non_liability_still_errors( self ):
        assets = Account( name = 'Assets', account_type = AccountType.ASSET )
        cash   = Account( name = 'Cash', parent = assets, handle = 'cash' )
        payoff = ScheduledLoanPayoff( event_date = date( 2030, 1, 1 ), loan = 'cash' )
        with self.assertRaises( MissingAccountError ):
            payoff.to_period_event( {}, self._chart( assets, cash ) )
