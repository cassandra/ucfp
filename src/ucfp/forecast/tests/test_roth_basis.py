"""Roth basis tracking and early-withdrawal taxation (issue #185).

A Roth carries a real basis -- its opening balance is 100% basis, plus contributions and conversions --
rather than seeding at zero basis like a pre-tax account. A withdrawal draws basis first, and the
earnings above basis are recognized in the owner's Roth Earnings account; withdrawn before 59-1/2 those
earnings are ordinary income plus a 10% early-withdrawal penalty, and at/after 59-1/2 they are tax-free.
These tests pin the basis seeding, basis-first ordering (including a full underwater draw),
contribution-to-basis routing, the owner-scoped earnings recognition, and the age-based tax and penalty
(single owner, a two-owner couple, and the age boundary).
"""
import unittest
from datetime import date
from decimal import Decimal

from common.rate import Rate
from ucfp.accounts.bookkeeper import Bookkeeper
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.accounts.money_utils import format_money
from ucfp.forecast.economic_outlook import EconomicOutlook, EconomicParameters
from ucfp.forecast.forecast import Forecast
from ucfp.forecast.parameters import (
    AssetParameters, ContributionSource, ForecastParameters, RetirementContribution,
    ScheduledRealization, Subject )
from ucfp.forecast.tests.tax_helpers import total_income_tax
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionType, StatuteForecastType
from ucfp.jurisdiction.law import StatuteProfile, TaxProjection
from ucfp.period.results import NoticeKind

_PROFILE = StatuteProfile( JurisdictionType.US_FEDERAL, TaxProjection( StatuteForecastType.CURRENT_LAW ) )
_SUBJECT = Subject( 'A', date( 1975, 1, 1 ), 'subject-a' )   # age 51 in 2026


def _parameters( *, events = (), outlook = None ):
    return ForecastParameters(
        start_date    = date( 2026, 1, 1 ),
        end_date      = date( 2026, 12, 31 ),
        filing_status = FilingStatus.SINGLE,
        statute       = _PROFILE,
        subjects      = [ _SUBJECT ],
        assets        = [
            AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
            # Opening 100k, all basis (cost_basis = opening) -- accepted now that Roth is not zero-basis.
            AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '100000' ), Decimal( '100000' ),
                             handle = 'roth', owner_handle = 'subject-a' ) ],
        events        = list( events ),
        economic_outlook = outlook if outlook is not None else EconomicOutlook(),
    )


class RothBasisSeedingTests( unittest.TestCase ):
    """A Roth seeds its opening balance as basis (cost), not as unrealized gain."""

    def test_roth_accepts_a_nonzero_basis_and_seeds_cost_at_opening( self ):
        # Before phase 2a a Roth with cost_basis != 0 was rejected by the zero-basis rule; now its
        # opening balance is basis, so the holding seeds cost = opening and valuation = 0.
        reader  = Bookkeeper( Forecast( _parameters() ).run().books )
        roth    = reader.chart.account( 'roth' )
        through = date( 2026, 12, 31 )
        self.assertEqual( reader.ledger.natural_balance( roth, through = through ), Decimal( '100000' ) )
        self.assertEqual( reader.ledger.market_value( roth, through = through ), Decimal( '100000' ) )


class RothUnderwaterFullWithdrawalTests( unittest.TestCase ):
    """A full withdrawal of an underwater Roth (basis above market) draws the whole basis and realizes the
    loss, clearing BOTH cost and valuation -- rather than stranding phantom basis against a negative mark.
    A stranded, inflated basis would later absorb real earnings and silently under-tax them (#185 review)."""

    _DECLINE = EconomicOutlook.constant(
        EconomicParameters( retirement_growth = Rate( Decimal( '-0.30' ) ) ) )

    def test_full_underwater_withdrawal_strands_no_basis_or_valuation( self ):
        # 100k basis declines 30% to 70k market; a full withdrawal (100k caps to the 70k market) must zero
        # the holding entirely -- pre-fix it left cost = 30k and valuation = -30k stranded (netting to a 0
        # market that hid the phantom pair).
        reader    = Bookkeeper( Forecast( _parameters(
            outlook = self._DECLINE,
            events  = [ ScheduledRealization( date( 2026, 12, 1 ), 'roth', Decimal( '100000' ) ) ] ) ).run().books )
        roth      = reader.chart.account( 'roth' )
        valuation = reader.chart.valuation_of( roth )
        through   = date( 2026, 12, 31 )
        self.assertEqual( reader.ledger.natural_balance( roth, through = through ), Decimal( '0' ) )
        self.assertEqual( reader.ledger.natural_balance( valuation, through = through ), Decimal( '0' ) )
        self.assertEqual( reader.ledger.market_value( roth, through = through ), Decimal( '0' ) )


class RothBasisFirstOrderingTests( unittest.TestCase ):
    """A Roth withdrawal draws basis (cost) before earnings (valuation): a withdrawal within basis
    realizes no gain, and only the excess above basis is recognized as earnings. Opening 100k basis
    grows 50% to 150k (50k earnings)."""

    _GROWTH_50 = EconomicOutlook.constant(
        EconomicParameters( retirement_growth = Rate( Decimal( '0.50' ) ) ) )

    def _realized_earnings( self, withdrawal ):
        reader = Bookkeeper( Forecast( _parameters(
            outlook = self._GROWTH_50,
            events  = [ ScheduledRealization( date( 2026, 12, 1 ), 'roth', withdrawal ) ] ) ).run().books )
        earnings = reader.chart.income_account( IncomeTaxClass.ROTH_EARNINGS, 'subject-a' )
        return reader.ledger.natural_balance( earnings )

    def test_withdrawal_within_basis_recognizes_no_earnings( self ):
        # drawing exactly the 100k basis (of a 150k balance) realizes no gain -- pro-rata would have
        # recognized 100k * 50k/150k = 33,333 of earnings.
        self.assertEqual( self._realized_earnings( Decimal( '100000' ) ), Decimal( '0' ) )

    def test_withdrawal_above_basis_recognizes_only_the_excess( self ):
        # drawing 120k exhausts the 100k basis and recognizes exactly the 20k above it as earnings.
        self.assertEqual( self._realized_earnings( Decimal( '120000' ) ), Decimal( '20000' ) )


class RothContributionBuildsBasisTests( unittest.TestCase ):
    """A Roth contribution is basis: it builds the holding's cost (not its valuation companion, where a
    pre-tax contribution lands), so the contributed principal comes out tax-free ahead of any earnings."""

    def _reader( self, events = () ):
        params = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _PROFILE,
            subjects      = [ _SUBJECT ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '50000' ), Decimal( '50000' ),
                                 handle = 'cash' ),
                AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '0' ), Decimal( '0' ),
                                 handle = 'roth', owner_handle = 'subject-a' ) ],
            contributions = [
                RetirementContribution( 'roth', Decimal( '7000' ), ContributionSource.PERSONAL ) ],
            events        = list( events ),
            economic_outlook = EconomicOutlook(),
        )
        return Bookkeeper( Forecast( params ).run().books )

    def test_contribution_builds_cost_basis( self ):
        # the 7000 contribution lands in the holding's cost (basis), not the valuation companion
        reader = self._reader()
        roth   = reader.chart.account( 'roth' )
        self.assertEqual( reader.ledger.natural_balance( roth, through = date( 2026, 12, 31 ) ),
                          Decimal( '7000' ) )

    def test_withdrawing_the_contribution_recognizes_no_earnings( self ):
        # withdrawing the contributed 7000 is entirely basis -> no earnings recognized
        reader   = self._reader(
            events = [ ScheduledRealization( date( 2026, 12, 1 ), 'roth', Decimal( '7000' ) ) ] )
        earnings = reader.chart.income_account( IncomeTaxClass.ROTH_EARNINGS, 'subject-a' )
        self.assertEqual( reader.ledger.natural_balance( earnings ), Decimal( '0' ) )


class RothEarningsRecognitionTests( unittest.TestCase ):
    """A Roth withdrawal's earnings are recognized in the OWNER's Roth Earnings account (not the
    household tax-free account), so the engine can read them per owner (for the age-based tax/penalty)."""

    _GROWTH_50 = EconomicOutlook.constant(
        EconomicParameters( retirement_growth = Rate( Decimal( '0.50' ) ) ) )

    def test_earnings_are_recognized_in_the_owner_account( self ):
        # withdraw 130k from a 150k Roth (100k basis) -> 30k earnings, in subject-a's Roth Earnings
        reader   = Bookkeeper( Forecast( _parameters(
            outlook = self._GROWTH_50,
            events  = [ ScheduledRealization( date( 2026, 12, 1 ), 'roth', Decimal( '130000' ) ) ] ) ).run().books )
        earnings = reader.chart.income_account( IncomeTaxClass.ROTH_EARNINGS, 'subject-a' )
        self.assertEqual( reader.ledger.natural_balance( earnings ), Decimal( '30000' ) )


class RothEarlyWithdrawalTaxTests( unittest.TestCase ):
    """Phase 4: Roth earnings withdrawn before 59.5 are ordinary income plus a 10% penalty; at/after
    59.5 they are tax-free. Basis is always free. A 100k-basis Roth grows 50% to 150k, and a 130k
    withdrawal draws the 100k basis first, leaving 30k of earnings."""

    _GROWTH_50 = EconomicOutlook.constant(
        EconomicParameters( retirement_growth = Rate( Decimal( '0.50' ) ) ) )

    def _reader( self, *, birthdate, withdrawal = Decimal( '130000' ) ):
        subject = Subject( 'A', birthdate, 'subject-a' )
        params  = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _PROFILE,
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'roth', owner_handle = 'subject-a' ) ],
            events        = [ ScheduledRealization( date( 2026, 12, 1 ), 'roth', withdrawal ) ],
            economic_outlook = self._GROWTH_50,
        )
        return Bookkeeper( Forecast( params ).run().books )

    def _penalty( self, reader ):
        return reader.ledger.natural_balance(
            reader.chart.expense_account( ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY ) )

    def test_pre_59_earnings_are_taxed_and_penalized( self ):
        reader = self._reader( birthdate = date( 1975, 1, 1 ) )   # age 51 in 2026
        self.assertEqual( self._penalty( reader ), Decimal( '3000' ) )        # 10% of the 30k earnings
        self.assertGreater( total_income_tax( reader ), Decimal( '0' ) )      # 30k earnings taxed as ordinary
        # the penalty's memo surfaces that the earnings were taxed as income, not merely penalized
        penalty_acct = reader.chart.expense_account( ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY )
        memo = next( t.description for t in reader.books.transactions
                     if any( e.account is penalty_acct for e in t.entries ) )
        self.assertIn( 'Roth earnings', memo )
        self.assertIn( 'taxed as ordinary income', memo )

    def test_post_59_earnings_are_tax_free( self ):
        reader = self._reader( birthdate = date( 1955, 1, 1 ) )   # age 71 in 2026 (>= 59.5)
        self.assertEqual( self._penalty( reader ), Decimal( '0' ) )
        self.assertEqual( total_income_tax( reader ), Decimal( '0' ) )

    def test_basis_withdrawal_is_free_even_before_59( self ):
        # a 90k withdrawal is entirely within the 100k basis -> no earnings, no tax, no penalty
        reader = self._reader( birthdate = date( 1975, 1, 1 ), withdrawal = Decimal( '90000' ) )
        self.assertEqual( self._penalty( reader ), Decimal( '0' ) )
        self.assertEqual( total_income_tax( reader ), Decimal( '0' ) )

    def test_age_59_earnings_are_early( self ):
        # `age` is an integer calendar-year age (year - birth_year) compared to a 59-1/2 limit, so the
        # whole year of turning 59 is "early": age 59 is under 59.5, taxed and penalized.
        reader = self._reader( birthdate = date( 1967, 1, 1 ) )   # age 59 in 2026
        self.assertEqual( self._penalty( reader ), Decimal( '3000' ) )
        self.assertGreater( total_income_tax( reader ), Decimal( '0' ) )

    def test_age_60_earnings_are_qualified( self ):
        # age 60 clears the 59-1/2 limit, so the same withdrawal is entirely free -- the integer age
        # makes the effective cutoff the year of turning 60, not a literal mid-year 59-1/2 crossing.
        reader = self._reader( birthdate = date( 1966, 1, 1 ) )   # age 60 in 2026
        self.assertEqual( self._penalty( reader ), Decimal( '0' ) )
        self.assertEqual( total_income_tax( reader ), Decimal( '0' ) )

    def test_crossover_withdrawal_memo_names_the_basis_and_earnings_split( self ):
        # the 130k draw (100k basis + 30k earnings) names its split so the income leg is explained
        reader        = self._reader( birthdate = date( 1975, 1, 1 ) )
        roth_earnings = reader.chart.income_account( IncomeTaxClass.ROTH_EARNINGS, 'subject-a' )
        withdrawals   = [ t for t in reader.books.transactions
                          if any( e.account is roth_earnings for e in t.entries ) ]
        self.assertEqual( len( withdrawals ), 1 )
        description = withdrawals[ 0 ].description
        self.assertIn( f'{format_money( Decimal( "100000" ) )} basis', description )
        self.assertIn( f'{format_money( Decimal( "30000" ) )} earnings', description )


class RothEarlyWithdrawalTwoOwnerTests( unittest.TestCase ):
    """With two owners, each Roth's earnings are taxed and penalized by that owner's OWN age: a younger
    owner's early withdrawal is taxed + penalized while an older owner's identical withdrawal is free, with
    no cross-attribution -- the whole point of the owner-scoped earnings recognition."""

    _GROWTH_50 = EconomicOutlook.constant(
        EconomicParameters( retirement_growth = Rate( Decimal( '0.50' ) ) ) )

    def _reader( self ):
        young  = Subject( 'Young', date( 1975, 1, 1 ), 'subject-a' )   # age 51 in 2026 (< 59-1/2)
        old    = Subject( 'Old', date( 1955, 1, 1 ), 'subject-b' )     # age 71 in 2026 (>= 59-1/2)
        params = ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.MARRIED_JOINT,
            statute       = _PROFILE,
            subjects      = [ young, old ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters( 'Roth A', AssetClass.ROTH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'roth-a', owner_handle = 'subject-a' ),
                AssetParameters( 'Roth B', AssetClass.ROTH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'roth-b', owner_handle = 'subject-b' ) ],
            events        = [
                ScheduledRealization( date( 2026, 12, 1 ), 'roth-a', Decimal( '130000' ) ),
                ScheduledRealization( date( 2026, 12, 1 ), 'roth-b', Decimal( '130000' ) ) ],
            economic_outlook = self._GROWTH_50,
        )
        return Bookkeeper( Forecast( params ).run().books )

    def test_each_owner_is_taxed_by_their_own_age( self ):
        reader     = self._reader()
        # both owners' 30k of earnings are recognized in their own Roth Earnings accounts ...
        earnings_a = reader.chart.income_account( IncomeTaxClass.ROTH_EARNINGS, 'subject-a' )
        earnings_b = reader.chart.income_account( IncomeTaxClass.ROTH_EARNINGS, 'subject-b' )
        self.assertEqual( reader.ledger.natural_balance( earnings_a ), Decimal( '30000' ) )
        self.assertEqual( reader.ledger.natural_balance( earnings_b ), Decimal( '30000' ) )
        # ... but only the younger owner's earnings are penalized (10% of 30k). If the older owner's were
        # wrongly penalized, or both owners' were summed against one age, the penalty would be 6000.
        penalty = reader.ledger.natural_balance(
            reader.chart.expense_account( ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY ) )
        self.assertEqual( penalty, Decimal( '3000' ) )


class RothIsNeverRmdTests( unittest.TestCase ):
    """A Roth is exempt from lifetime RMDs (unlike a pre-tax account), so a Roth held past the RMD age
    forces no distribution -- confirmed while the surrounding retirement code is in flux (#185)."""

    def test_roth_at_rmd_age_forces_no_distribution( self ):
        subject = Subject( 'A', date( 1950, 1, 1 ), 'subject-a' )   # age 76 in 2026, past RMD start
        result  = Forecast( ForecastParameters(
            start_date    = date( 2026, 1, 1 ),
            end_date      = date( 2026, 12, 31 ),
            filing_status = FilingStatus.SINGLE,
            statute       = _PROFILE,
            subjects      = [ subject ],
            assets        = [
                AssetParameters( 'Cash', AssetClass.CASH, Decimal( '0' ), Decimal( '0' ), handle = 'cash' ),
                AssetParameters( 'Roth', AssetClass.ROTH, Decimal( '100000' ), Decimal( '100000' ),
                                 handle = 'roth', owner_handle = 'subject-a' ) ],
        ) ).run()
        rmd_notices = [ notice for step in result.steps for notice in step.result.notices
                        if notice.kind == NoticeKind.REQUIRED_MINIMUM_DISTRIBUTION ]
        self.assertEqual( rmd_notices, [] )
        reader = Bookkeeper( result.books )
        self.assertEqual(
            reader.ledger.market_value( reader.chart.account( 'roth' ), through = date( 2026, 12, 31 ) ),
            Decimal( '100000' ) )


if __name__ == '__main__':
    unittest.main()
