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
from ucfp.jurisdiction.us.subdivision_tax import StateIncomeTax

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


if __name__ == '__main__':
    unittest.main()
