"""The simplified state income tax (#111): a flat rate on federal AGI, less the state's exemption of
retirement income (Social Security, pensions, pre-tax withdrawals). Exercises the exemption formula
directly with a synthetic `StateIncomeTax` policy and a minimal fiscal-window stub -- the per-state
fractions and their wiring are covered separately."""
import unittest
from decimal import Decimal

from common.rate import Rate

from ucfp.accounts.enums import IncomeTaxClass
from ucfp.jurisdiction.us.engine import USFederalTaxEngine
from ucfp.jurisdiction.us.parameters import federal_2026
from ucfp.jurisdiction.us.subdivision_tax import (
    StateIncomeTax, USState, exemption_words, state_tax_policy )

_D = Decimal


class _Window:
    """A fiscal-window stub returning fixed pension / retirement-distribution income; every other
    class is zero (the charge only reads those two, plus the AGI and taxable-SS passed in directly)."""

    def __init__( self, pension = _D( '0' ), retirement_distribution = _D( '0' ) ):
        self._by_class = {
            IncomeTaxClass.PENSION                 : pension,
            IncomeTaxClass.RETIREMENT_DISTRIBUTION : retirement_distribution,
        }

    def income( self, income_tax_class ):
        return self._by_class.get( income_tax_class, _D( '0' ) )


def _charge( policy, agi, taxable_ss = _D( '0' ), pension = _D( '0' ), retirement_distribution = _D( '0' ) ):
    engine = USFederalTaxEngine( federal_2026(), policy )
    window = _Window( pension = _D( pension ), retirement_distribution = _D( retirement_distribution ) )
    return engine._state_income_tax_charge( window, _D( agi ), _D( taxable_ss ) )


_FIVE_PCT = StateIncomeTax( rate = Rate.percent( _D( '5' ) ) )   # no exemptions -- the flat model


class StateIncomeTaxTest( unittest.TestCase ):

    def test_flat_rate_on_agi_with_no_exemptions( self ):
        self.assertEqual( _charge( _FIVE_PCT, '100000' ), _D( '5000.00' ) )

    def test_social_security_exemption_removes_taxable_ss_from_the_base( self ):
        policy = StateIncomeTax( rate = Rate.percent( _D( '5' ) ), social_security_exempt = _D( '1' ) )
        self.assertEqual( _charge( policy, '100000', taxable_ss = '20000' ), _D( '4000.00' ) )   # 5% of 80k

    def test_retirement_exemption_removes_pension_and_withdrawals( self ):
        policy = StateIncomeTax( rate = Rate.percent( _D( '5' ) ), retirement_exempt = _D( '1' ) )
        charge = _charge( policy, '100000', pension = '30000', retirement_distribution = '10000' )
        self.assertEqual( charge, _D( '3000.00' ) )                                              # 5% of 60k

    def test_both_exemptions_stack( self ):
        policy = StateIncomeTax( rate = Rate.percent( _D( '5' ) ),
                                 social_security_exempt = _D( '1' ), retirement_exempt = _D( '1' ) )
        charge = _charge( policy, '100000', taxable_ss = '20000', pension = '30000',
                          retirement_distribution = '10000' )
        self.assertEqual( charge, _D( '2000.00' ) )                                              # 5% of 40k

    def test_partial_retirement_exemption( self ):
        policy = StateIncomeTax( rate = Rate.percent( _D( '5' ) ), retirement_exempt = _D( '0.5' ) )
        self.assertEqual( _charge( policy, '100000', pension = '40000' ), _D( '4000.00' ) )      # 5% of 80k

    def test_base_floors_at_zero_when_exemptions_exceed_agi( self ):
        policy = StateIncomeTax( rate = Rate.percent( _D( '5' ) ),
                                 social_security_exempt = _D( '1' ), retirement_exempt = _D( '1' ) )
        self.assertEqual(
            _charge( policy, '30000', taxable_ss = '20000', retirement_distribution = '40000' ), _D( '0' ) )

    def test_zero_rate_is_no_tax( self ):
        self.assertEqual( _charge( StateIncomeTax(), '100000', pension = '40000' ), _D( '0' ) )


class PerStatePolicyTest( unittest.TestCase ):
    """`state_tax_policy` resolves the chosen state's retirement-income exemptions and carries the
    household's (overridable) rate. Values are coarse per-state approximations."""

    def test_no_state_is_a_flat_rate_with_no_exemptions( self ):
        policy = state_tax_policy( None, Rate.percent( _D( '5' ) ) )
        self.assertEqual( policy.social_security_exempt, _D( '0' ) )
        self.assertEqual( policy.retirement_exempt, _D( '0' ) )

    def test_the_overridable_rate_is_carried_through( self ):
        self.assertEqual(
            state_tax_policy( USState.ILLINOIS, Rate.percent( _D( '3.5' ) ) ).rate,
            Rate.percent( _D( '3.5' ) ) )

    def test_full_exemption_state_leaves_a_retiree_no_state_tax( self ):
        # Illinois exempts Social Security, pensions, and withdrawals: a retiree living on them owes ~none.
        policy = state_tax_policy( USState.ILLINOIS, Rate.percent( _D( '5' ) ) )
        self.assertEqual(
            ( policy.social_security_exempt, policy.retirement_exempt ), ( _D( '1.0' ), _D( '1.0' ) ) )
        engine = USFederalTaxEngine( federal_2026(), policy )
        window = _Window( pension = _D( '30000' ) )                # AGI = 20k taxable SS + 30k pension
        self.assertEqual( engine._state_income_tax_charge( window, _D( '50000' ), _D( '20000' ) ), _D( '0' ) )

    def test_social_security_exempt_state_still_taxes_pension_income( self ):
        # California exempts Social Security but fully taxes retirement income.
        policy = state_tax_policy( USState.CALIFORNIA, Rate.percent( _D( '5' ) ) )
        self.assertEqual(
            ( policy.social_security_exempt, policy.retirement_exempt ), ( _D( '1.0' ), _D( '0.0' ) ) )
        engine = USFederalTaxEngine( federal_2026(), policy )
        window = _Window( pension = _D( '30000' ) )
        # SS (20k) exempt, pension (30k) taxed -> 5% of 30k
        self.assertEqual(
            engine._state_income_tax_charge( window, _D( '50000' ), _D( '20000' ) ), _D( '1500.00' ) )

    def test_exemption_words_read_out_the_status( self ):
        # the read-only UI summary: fraction 1 -> Exempt, 0.5 -> Partially exempt, 0 -> Taxed
        self.assertEqual( exemption_words( USState.ILLINOIS ), ( 'Exempt', 'Exempt' ) )
        self.assertEqual( exemption_words( USState.CALIFORNIA ), ( 'Exempt', 'Taxed' ) )
        self.assertEqual( exemption_words( USState.CONNECTICUT ), ( 'Partially exempt', 'Partially exempt' ) )


if __name__ == '__main__':
    unittest.main()
