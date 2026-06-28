"""Committed regression suite for granularity invariance (issue #16).

The Forecast engine promises that the same parameters run at any interval length. This suite
locks the *contract* that promise actually entails -- derived and validated in the issue-#16
audit -- so a future month-vs-year regression fails loudly here:

- **Rate flows are granularity-invariant.** Pure-stream income/expense classes (wages, Social
  Security, gross rental, living) -- those sourced only from `IncomeStream` / `ExpenseStream` --
  match across granularities to rounding, before any run depletes. RENTAL_EXPENSE is excluded: a
  rental mortgage's interest nets into it (Schedule E), and loan amortization splits legitimately
  drift month-vs-year, so the class is no longer purely stream-sourced.
- **Occurrence flows are year-total-invariant.** A cost with a real cadence (`ExpenseItem` +
  `Recurrence`, e.g. property tax) places its occurrences differently within a year at different
  granularities, but the year total is the same.
- **Zero-dynamics runs are identical.** At the null tier (no economic rates, no funding policy) a
  loan-free profile's year-end net worth matches across granularities to rounding -- the check
  that would have caught the expense-lumping defect this suite was born from.
- **Outcomes hold to the materiality bar.** Depletion year is identical across granularities at
  the null and growth tiers; at the funding/full tiers (real draws) it may differ by at most one
  year, and refining the granularity converges (quarterly lies between annual and monthly).

What this suite deliberately does NOT assert as invariant -- legitimate may-drift documented in
`FORECAST_ENGINE.md`: draw/balance-driven income (ordinary withdrawals/RMDs, realized gains,
interest, dividends), loan amortization interest/principal splits, draw-frequency effects on
balances, and books carried flat after an early stop.
"""
import unittest
from decimal import Decimal

from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.tests.granularity_harness import GRANULARITIES, compare
from ucfp.forecast.tests.granularity_profiles import PROFILES, STARTS, TIERS

# Classes sourced only from smooth streams -> prorated, so granularity-invariant per year.
# RENTAL_EXPENSE is intentionally absent: a rental mortgage's interest nets into it (Schedule E),
# and loan amortization splits drift month-vs-year, so it is no longer a pure stream (see below).
_PURE_STREAM_INCOME  = ( IncomeTaxClass.WAGES, IncomeTaxClass.SOCIAL_SECURITY, IncomeTaxClass.GROSS_RENTAL )
_PURE_STREAM_EXPENSE = ( ExpenseTaxClass.LIVING, )

# Tiers by how much legitimate divergence they admit (see granularity_profiles).
_LOW_TIERS     = ( 'null', 'growth' )     # outcomes must be identical across granularities
_FUNDING_TIERS = ( 'funding', 'full' )    # real draws: depletion year may differ by <= 1

_REL_TOL = Decimal( '1e-6' )              # rounding/quantization noise floor; real drift is >> this
_ZERO    = Decimal( '0' )


def _rel( reference : Decimal, other : Decimal ) -> Decimal:
    """Relative difference of `other` from `reference`, with a unit floor so near-zero figures
    compare absolutely (and never divide by zero)."""
    return abs( other - reference ) / max( abs( reference ), Decimal( '1' ) )


def _earliest_depletion( comparison : dict ):
    """The first year any granularity depletes (None if all survive the horizon) -- the point
    past which a stopped run carries flat books, so flow/level invariants no longer apply."""
    years = [ outcome.depletion_year for _figures, outcome in comparison.values()
              if outcome.depletion_year is not None ]
    return min( years ) if years else None


class GranularityInvarianceTest( unittest.TestCase ):

    def test_pure_stream_flows_invariant_across_granularity( self ):
        """Stream-sourced income/expense classes match across granularities to rounding, every
        pre-depletion year, for every profile, tier, and start (January or mid-year) -- the
        rate-flow invariant, which a partial first year must also honor."""
        for profile_name, build in PROFILES.items():
            for tier_name, transform in TIERS.items():
                for start_name, start in STARTS.items():
                    comparison = compare( start( transform( build() ) ) )
                    cutoff     = _earliest_depletion( comparison )
                    annual     = { figures.year : figures for figures in comparison[ 'annual' ][ 0 ] }
                    label      = f'{profile_name}/{start_name}'
                    for granularity_name, _ in GRANULARITIES:
                        other = { figures.year : figures for figures in comparison[ granularity_name ][ 0 ] }
                        for year, annual_figures in annual.items():
                            if cutoff is not None and year >= cutoff:
                                continue
                            for income_class in _PURE_STREAM_INCOME:
                                self._assert_close(
                                    annual_figures.income.get( income_class, _ZERO ),
                                    other[ year ].income.get( income_class, _ZERO ),
                                    label, tier_name, granularity_name, year, income_class.name )
                            for expense_class in _PURE_STREAM_EXPENSE:
                                self._assert_close(
                                    annual_figures.expense.get( expense_class, _ZERO ),
                                    other[ year ].expense.get( expense_class, _ZERO ),
                                    label, tier_name, granularity_name, year, expense_class.name )
                            continue
                        continue
                    continue
                continue
            continue

    def test_occurrence_year_totals_invariant_across_granularity( self ):
        """An occurrence cost (the wage_earner's annual property tax, a SALT `ExpenseItem`) places
        its lump differently within a year at finer granularity, but the year total is unchanged --
        from a January or a mid-year start."""
        for start_name, start in STARTS.items():
            comparison = compare( start( TIERS[ 'null' ]( PROFILES[ 'wage_earner' ]() ) ) )
            annual     = { figures.year : figures for figures in comparison[ 'annual' ][ 0 ] }
            for granularity_name, _ in GRANULARITIES:
                other = { figures.year : figures for figures in comparison[ granularity_name ][ 0 ] }
                for year, annual_figures in annual.items():
                    self._assert_close(
                        annual_figures.expense.get( ExpenseTaxClass.SALT, _ZERO ),
                        other[ year ].expense.get( ExpenseTaxClass.SALT, _ZERO ),
                        f'wage_earner/{start_name}', 'null', granularity_name, year, 'SALT' )
                    continue
                continue
            continue

    def test_income_item_year_totals_invariant_across_granularity( self ):
        """The occurrence-income shapes -- a recurring IncomeItem and a one-time IncomeItem --
        place differently within a year at finer granularity, but their year totals hold. The
        gig_worker's ORDINARY income is sourced only from items (no pre-tax withdrawals contaminate
        it), so it must match across granularities at every tier and start."""
        for tier_name, transform in TIERS.items():
            for start_name, start in STARTS.items():
                comparison = compare( start( transform( PROFILES[ 'gig_worker' ]() ) ) )
                annual     = { figures.year : figures for figures in comparison[ 'annual' ][ 0 ] }
                for granularity_name, _ in GRANULARITIES:
                    other = { figures.year : figures for figures in comparison[ granularity_name ][ 0 ] }
                    for year, annual_figures in annual.items():
                        self._assert_close(
                            annual_figures.income.get( IncomeTaxClass.ORDINARY, _ZERO ),
                            other[ year ].income.get( IncomeTaxClass.ORDINARY, _ZERO ),
                            f'gig_worker/{start_name}', tier_name, granularity_name, year, 'ORDINARY' )
                        continue
                    continue
                continue
            continue

    def test_null_tier_loan_free_net_worth_invariant( self ):
        """With zero economics and no funding policy, a loan-free profile is fully deterministic:
        year-end net worth matches across granularities to rounding. This is the check the
        expense-lumping defect (#16) would have tripped -- any flow that lumps instead of
        prorating shows here as a within-year net-worth divergence -- from either start."""
        for profile_name, build in PROFILES.items():
            for start_name, start in STARTS.items():
                parameters = start( TIERS[ 'null' ]( build() ) )
                if parameters.loans:                   # loan amortization legitimately drifts; skip
                    continue
                comparison = compare( parameters )
                cutoff     = _earliest_depletion( comparison )
                annual     = { figures.year : figures for figures in comparison[ 'annual' ][ 0 ] }
                for granularity_name, _ in GRANULARITIES:
                    other = { figures.year : figures for figures in comparison[ granularity_name ][ 0 ] }
                    for year, annual_figures in annual.items():
                        if cutoff is not None and year >= cutoff:
                            continue
                        self._assert_close(
                            annual_figures.net_worth, other[ year ].net_worth,
                            f'{profile_name}/{start_name}', 'null', granularity_name, year, 'net_worth' )
                        continue
                    continue
                continue
            continue

    def test_depletion_year_identical_at_low_tiers( self ):
        """At the null and growth tiers (no funding draws), the depletion outcome is identical
        across every granularity, from either start -- the strongest form of the materiality bar."""
        for profile_name, build in PROFILES.items():
            for tier_name in _LOW_TIERS:
                for start_name, start in STARTS.items():
                    comparison = compare( start( TIERS[ tier_name ]( build() ) ) )
                    years = { name : outcome.depletion_year
                              for name, ( _figures, outcome ) in comparison.items() }
                    with self.subTest( profile = profile_name, tier = tier_name, start = start_name ):
                        self.assertEqual(
                            len( set( years.values() ) ), 1,
                            f'{profile_name}/{tier_name}/{start_name}: depletion year differs across '
                            f'granularity: {years}' )
                    continue
                continue
            continue

    def test_depletion_year_within_one_at_funding_tiers( self ):
        """At the funding/full tiers, draw-frequency drift may move depletion by at most one year;
        refining the granularity converges (quarterly agrees with monthly). Holds from either start."""
        for profile_name, build in PROFILES.items():
            for tier_name in _FUNDING_TIERS:
                for start_name, start in STARTS.items():
                    comparison = compare( start( TIERS[ tier_name ]( build() ) ) )
                    years = [ outcome.depletion_year for _figures, outcome in comparison.values()
                              if outcome.depletion_year is not None ]
                    if not years:
                        continue
                    with self.subTest( profile = profile_name, tier = tier_name, start = start_name ):
                        self.assertLessEqual(
                            max( years ) - min( years ), 1,
                            f'{profile_name}/{tier_name}/{start_name}: depletion year spans more than '
                            f'one year: {[ ( n, o.depletion_year ) for n, ( _f, o ) in comparison.items() ]}' )
                    continue
                continue
            continue

    def test_finer_granularity_converges_on_terminal_net_worth( self ):
        """Refining is monotonic: quarterly terminal net worth lies between annual and monthly
        (within rounding). Asserted on the combos that survive the horizon, where there is no
        post-depletion carry to muddy the terminal figure. Checked from either start."""
        for profile_name, build in PROFILES.items():
            for tier_name, transform in TIERS.items():
                for start_name, start in STARTS.items():
                    comparison = compare( start( transform( build() ) ) )
                    if _earliest_depletion( comparison ) is not None:
                        continue
                    annual    = comparison[ 'annual' ][ 1 ].terminal_net_worth
                    quarterly = comparison[ 'quarterly' ][ 1 ].terminal_net_worth
                    monthly   = comparison[ 'monthly' ][ 1 ].terminal_net_worth
                    low, high = min( annual, monthly ), max( annual, monthly )
                    slack     = max( abs( high ), Decimal( '1' ) ) * _REL_TOL
                    with self.subTest( profile = profile_name, tier = tier_name, start = start_name ):
                        self.assertTrue(
                            low - slack <= quarterly <= high + slack,
                            f'{profile_name}/{tier_name}/{start_name}: quarterly terminal net worth '
                            f'{quarterly} not between annual {annual} and monthly {monthly}' )
                    continue
                continue
            continue

    def _assert_close( self, reference, other, profile, tier, granularity, year, label ):
        difference = _rel( reference, other )
        self.assertLessEqual(
            difference, _REL_TOL,
            f'{profile}/{tier} {granularity} {year} {label}: {other} vs annual {reference} '
            f'(relative {difference})' )
        return
