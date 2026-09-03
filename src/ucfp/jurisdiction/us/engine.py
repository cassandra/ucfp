"""The US federal income-tax engine.

`USFederalTaxEngine` replaces `ZeroTaxEngine` with the real federal pipeline: an
ordered DAG over a fiscal year's income that yields the tax charges. The engine owns
the *structure* (the stages and their dependencies); the projectable *values* for
the year are the `TaxParameters` it is constructed with, so the Scenario builds one
engine per projected year (indexing the baseline for inflation, or applying a
what-if such as a rate hike).

Pipeline (strict DAG): property-sale adjustments from `TaxContext.properties` (§121
residence-gain exclusion; §1250 rental depreciation recapture from the deterministic
schedule) -> capital-gains netting (short vs long, with the prior year's
loss carryover applied first, character-preserving) -> Social-Security taxability
worksheet -> AGI -> the simplified state income tax (a flat function of AGI, so it lands
here) -> the greater of the standard and itemized deductions (the state income tax joins
SALT) -> split taxable income across rate buckets -> tax on the stack -> the 3.8% net investment
income tax (NIIT, on its own MAGI) -> employee FICA on wages -> the ACA premium tax
credit (a refundable credit, on its own MAGI) -> total -> charges + credits, plus the
loss carryover to thread forward. AGI and the modified-AGI variants are surfaced as
`TaxFigures` on the assessment (see `figures.py`); NIIT uses `niit_magi`, the PTC uses
`aca_magi`, and `irmaa_magi` is ready for the Scenario's IRMAA.

A simplified state income tax rides alongside: a flat rate (the engine's `state_income_tax`
policy, no tax by default) on federal AGI less the state's exemption of retirement income
(taxable Social Security, pensions, and pre-tax withdrawals), booked as its own
`STATE_INCOME_TAX` charge. It reads AGI and feeds one federal figure -- it joins the SALT
itemized deduction (capped) -- but nothing feeds back to it, so the pipeline stays acyclic.
Flat and unprojected, so it is an engine argument rather than a `TaxParameters` field. This is
not a model of any state's real tax (no brackets, real deductions, or credits); see
`subdivision_tax.py`.

The stack, bottom to top: ordinary income at ordinary brackets; then the §1250 (25%)
and collectibles (28%) maximum-rate long-term gains, each taxed at ordinary rates
stacked on ordinary income but capped at its maximum rate; then the 0/15/20%
preferential gains (qualified dividends + regular long-term gains) at the LTCG
brackets stacked on top of everything ordinary-rated. Stacking via
`table.tax_on(base + bucket) - table.tax_on(base)` spans rate boundaries correctly.

Net rental income (gross rents minus operating expenses minus depreciation computed
from each rental's attributes) is ordinary income and net investment income, after the
passive-activity-loss rules: a net rental loss is deductible against other income only
up to the active-participation special allowance (phased out over MAGI), and the excess
is suspended and carried forward in `TaxState` (netting against future passive income),
then released in full when the rental activity is fully disposed.

AGGREGATE-RENTAL ASSUMPTION: all rentals are treated as one passive activity with
uniform active participation (a single household flag). This is exact for a single
rental or several uniformly-participated ones; a MIX of active and passive rentals is not
supported, so the Scenario must not create non-actively-participated rentals.

NOT MODELED (none of which change this contract): cross-category capital-loss absorption
(a net loss should reduce 28% then 25% then 0/15/20% gains -- the §1250/collectibles
buckets are excluded from the ST/LT netting, only their gains are taxed); per-property /
mixed passive-activity participation (above); the foreign-earned-income exclusion add-back
(a MAGI component treated as zero); the mortgage acquisition-debt limit and the charitable
5-year carryover; ACA refinements (advance-PTC reconciliation, enrollment-month proration,
the under-100%-FPL Medicaid floor). Deliberate simplifications:
RMDs are forced per pre-tax account, not aggregated across a person's IRAs;
the senior-deduction phase-out keys on AGI, not its own MAGI; depreciation prorates by
elapsed days, not the §168 mid-month convention. §1250 recapture and a rental's long-term gain
are aggregated across rentals sold in a year (per the single-activity assumption), not split
per property.
"""
from decimal import Decimal
from typing import Iterator, NamedTuple, Optional

from common.date_span import DateSpan
from ucfp.accounts.books import Account
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.accounts.money_utils import format_money
from ucfp.jurisdiction.brackets import BracketTable
from ucfp.jurisdiction.engine import (
    ContributionKind,
    FiscalWindowView,
    ForcedTransaction,
    TaxAssessment,
    TaxCharge,
    TaxCredit,
    TaxEngine,
    TaxPenalty,
)

from ucfp.jurisdiction.context import TaxContext, TaxSubject
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.jurisdiction.subsidized_health import SubsidizedHealthEnrollment

from . import rmd
from .depreciation import accumulated_depreciation, period_depreciation
from .figures import TaxFigures
from .filing import resolve_filing_status
from .parameters import StandardDeduction, TaxParameters
from .tax_worksheet import TaxYearInputs, build_worksheet
from .subdivision_tax import StateIncomeTax
from .state import CapitalLossCarryover, PassiveLossCarryover, TaxState

_ZERO        = Decimal( '0' )
_HALF        = Decimal( '0.5' )
_SS_MAX_RATE = Decimal( '0.85' )


class _NetCapital( NamedTuple ):
    """The outcome of capital-gains netting: a net short-term gain taxed at ordinary
    rates, a net long-term gain taxed at preferential rates, the net loss applied
    against ordinary income this year (capped), and the loss to carry forward."""

    gain_ordinary     : Decimal
    gain_preferential : Decimal
    ordinary_offset   : Decimal
    carryover         : CapitalLossCarryover


class _TaxableSplit( NamedTuple ):
    """Taxable income apportioned across rate buckets. When the deduction exceeds
    ordinary income and eats into gains, the lowest-rate bucket is preserved first
    (collectibles reduced before §1250 before preferential), which is favorable and
    matches the worksheet ordering."""

    ordinary     : Decimal
    preferential : Decimal
    section_1250 : Decimal
    collectibles : Decimal


class _IncomeTaxParts( NamedTuple ):
    """The income tax split by rate layer -- ordinary brackets, preferential long-term gains, and the
    separately-capped §1250 and collectibles gains -- each a distinct account so the detail is visible.
    They sum to the total income tax; the split is exact, not an apportionment."""

    ordinary      : Decimal
    capital_gains : Decimal
    section_1250  : Decimal
    collectibles  : Decimal


class _PassiveActivity( NamedTuple ):
    """The passive-activity (rental) outcome: `deductible` is the amount flowing into
    ordinary income and net investment income (net passive income if positive, the
    allowed loss if negative); `suspended` is the disallowed loss carried forward."""

    deductible : Decimal
    suspended  : Decimal


class _RentalGainSplit( NamedTuple ):
    """A rental disposition's gain split for tax: the §1250 unrecaptured-depreciation portion (the
    25%-rate bucket) and the long-term remainder (the 0/15/20% bucket, possibly a loss). Recapture is
    capped at the total gain, so a rental sold at or below its adjusted basis recaptures less, or none."""

    section_1250 : Decimal
    long_term    : Decimal


class USFederalTaxEngine( TaxEngine ):
    """Assesses US federal income tax for one fiscal year against the parameters it
    is constructed with."""

    def __init__( self, parameters : TaxParameters,
                  state_income_tax : StateIncomeTax = StateIncomeTax() ):
        self._parameters       = parameters
        # A constructor argument, not a `TaxParameters` field: the flat state surcharge is never
        # COLA-indexed, so it is the same for every projected year. Default is no state tax.
        self._state_income_tax = state_income_tax

    def assess( self, fiscal_window : FiscalWindowView, tax_context : TaxContext,
                opening_tax_state : Optional[ TaxState ] ) -> TaxAssessment:
        # The context carries the household's standing filing status and the spouse death year;
        # the US surviving-spouse (QSS) rule derives the year's effective status from them.
        status     = resolve_filing_status(
            tax_context.filing_status, tax_context.spouse_death_year, fiscal_window.span.end_date.year )
        tax_state  = opening_tax_state or TaxState()
        carryover  = tax_state.capital_loss_carryover

        wages               = fiscal_window.income( IncomeTaxClass.WAGES )
        # Pensions and retirement distributions (RMDs, pre-tax withdrawals) are their own income lines
        # for the books but tax exactly as ordinary income, so they fold in here.
        # Roth earnings withdrawn before 59-1/2 are ordinary income (basis withdrawals and earnings at
        # 59-1/2+ are tax-free, so excluded); they also draw the 10% penalty in `assess_penalties`.
        ordinary_other      = ( fiscal_window.income( IncomeTaxClass.ORDINARY )
                                + fiscal_window.income( IncomeTaxClass.PENSION )
                                + fiscal_window.income( IncomeTaxClass.RETIREMENT_DISTRIBUTION )
                                + self._roth_early_earnings( fiscal_window, tax_context ) )
        taxable_interest    = fiscal_window.income( IncomeTaxClass.TAXABLE_INTEREST )
        tax_exempt_interest = fiscal_window.income( IncomeTaxClass.TAX_EXEMPT_INTEREST )
        qualified_dividends = fiscal_window.income( IncomeTaxClass.QUALIFIED_DIVIDENDS )
        ss_gross            = fiscal_window.income( IncomeTaxClass.SOCIAL_SECURITY )

        # A primary-residence sale realizes into its own account: §121 excludes up to the
        # filing-status cap, and the taxable remainder is taxed as a long-term gain (a
        # residence loss is personal and non-deductible, so the remainder floors at zero).
        # §1250 adds rental depreciation recapture to the 25% bucket.
        residence_gain   = max( _ZERO, fiscal_window.income( IncomeTaxClass.RESIDENCE_SECTION_121_GAIN ) )
        residence_exclusion = min( self._parameters.section_121_exclusion[ status ], residence_gain )
        # A second home is personal-use like the residence -- its gain floors at zero (a loss is
        # non-deductible) -- but gets no exclusion, so the whole floored gain is long-term.
        second_home_gain = max( _ZERO, fiscal_window.income( IncomeTaxClass.SECOND_HOME_GAIN ) )
        # A rental disposition's gain (its own class) splits into §1250 depreciation recapture and a
        # long-term remainder; recapture is capped at the actual total gain (see `_split_rental_gain`).
        rental = self._split_rental_gain(
            fiscal_window.income( IncomeTaxClass.RENTAL_SALE_GAIN ),
            self._depreciation_recapture( tax_context ) )
        long_term_gains  = (
            fiscal_window.income( IncomeTaxClass.LONG_TERM_GAINS )
            + ( residence_gain - residence_exclusion )
            + second_home_gain
            + rental.long_term )
        section_1250_gain = (
            fiscal_window.income( IncomeTaxClass.SECTION_1250_GAIN )
            + rental.section_1250 )

        net_short = fiscal_window.income( IncomeTaxClass.SHORT_TERM_GAINS ) - carryover.short
        net_long  = long_term_gains - carryover.long
        netted    = self._net_capital_gains( net_short, net_long )

        # The maximum-rate long-term gains have their own buckets and are excluded from the
        # ST/LT loss netting above; only their gains are taxed.
        section_1250 = max( _ZERO, section_1250_gain )
        collectibles = max( _ZERO, fiscal_window.income( IncomeTaxClass.COLLECTIBLES_GAINS ) )

        # Pre-tax retirement contributions from cash are an above-the-line deduction: they
        # reduce ordinary income here (so AGI, the Social Security worksheet, and every MAGI
        # downstream all see the reduction). FICA is unaffected -- it reads gross WAGES. The
        # employer match and Roth contributions are excluded by construction (not cash into a
        # pre-tax holding).
        pretax_contributions = self._pretax_contributions( fiscal_window )
        ordinary_nonrental  = ( wages + ordinary_other + taxable_interest
                                + netted.gain_ordinary - netted.ordinary_offset
                                - pretax_contributions )
        preferential_income = qualified_dividends + netted.gain_preferential
        total_gains         = preferential_income + section_1250 + collectibles

        # Rental income/loss runs through the passive-activity-loss rules: a loss is
        # deductible against other income only up to the active-participation allowance
        # (phased out over MAGI), with the excess suspended. The phase-out MAGI excludes
        # the rental loss itself (and Social Security), so it is the other-income total.
        net_rental = self._rental_net_income( fiscal_window, tax_context )
        passive    = self._passive_activity_result(
            net_rental, ordinary_nonrental + total_gains,
            tax_state.passive_loss_carryover.suspended, tax_context )
        ordinary_income = ordinary_nonrental + passive.deductible

        ss_worksheet_income = ordinary_income + total_gains + tax_exempt_interest
        taxable_ss = self._taxable_social_security( status, ss_gross, ss_worksheet_income )
        agi        = ordinary_income + total_gains + taxable_ss
        figures    = TaxFigures(
            agi                     = agi,
            tax_exempt_interest     = tax_exempt_interest,
            untaxed_social_security = ss_gross - taxable_ss,
        )
        # Computed before the deduction step because it feeds the SALT itemized deduction, then reused
        # as its own charge below. State tax depends only on AGI, so a single pass stays acyclic.
        state_income_tax = self._state_income_tax_charge( fiscal_window, agi, taxable_ss )
        standard_deduction = self._standard_deduction( status, tax_context, agi )
        deduction  = max(
            standard_deduction,
            self._itemized_deduction( fiscal_window, agi, state_income_tax ) )

        taxable_income = max( _ZERO, agi - deduction )
        split          = self._split_taxable_income(
            taxable_income, preferential_income, section_1250, collectibles )
        income_tax     = self._tax_on_stack( status, split )   # ordinary / gains / §1250 / collectibles

        net_investment_income = max(
            _ZERO,
            taxable_interest + qualified_dividends + passive.deductible + netted.gain_ordinary
            + netted.gain_preferential - netted.ordinary_offset + section_1250 + collectibles )
        niit = self._net_investment_income_tax(
            status, figures.niit_magi, net_investment_income )

        premium_credit = self._premium_tax_credit( figures.aca_magi, tax_context.health_enrollment )

        # Income tax splits into its rate layers, each its own account; NIIT stands apart. Employment
        # tax (FICA) is withheld in-year (see `assess_employment_tax`), not assessed here. The
        # refundable premium credit offsets the ordinary income tax (its natural home). Each charge
        # carries a memo scoped to its own layer's drivers (mirroring `TaxPenalty.reason`), which the
        # Period posts as the accrual's description so the results drill-down explains the tax.
        niit_threshold = self._parameters.niit_thresholds[ status ]
        niit_taxed     = min( net_investment_income, max( _ZERO, figures.niit_magi - niit_threshold ) )
        income_tax_charges = (
            ( ExpenseTaxClass.ORDINARY_INCOME_TAX, income_tax.ordinary,
              f'On {format_money( split.ordinary )} of ordinary taxable income '
              f'(AGI {format_money( agi )} less {format_money( deduction )} deduction).' ),
            ( ExpenseTaxClass.CAPITAL_GAINS_TAX, income_tax.capital_gains,
              f'On {format_money( preferential_income )} of long-term gains and qualified dividends.' ),
            ( ExpenseTaxClass.SECTION_1250_TAX, income_tax.section_1250,
              f'Recapture of {format_money( section_1250 )} of accumulated depreciation '
              'at the 25% §1250 rate.' ),
            ( ExpenseTaxClass.COLLECTIBLES_TAX, income_tax.collectibles,
              f'On {format_money( collectibles )} of collectibles gains at the 28% rate.' ),
            ( ExpenseTaxClass.NIIT, niit,
              f'{self._parameters.niit_rate:.1%} on {format_money( niit_taxed )} — the lesser of '
              f'{format_money( net_investment_income )} net investment income and MAGI '
              f'{format_money( figures.niit_magi )} over the {format_money( niit_threshold )} threshold.' ),
            ( ExpenseTaxClass.STATE_INCOME_TAX, state_income_tax,
              f'State income tax on {format_money( agi )} AGI (retirement income partly exempt).' ) )
        charges = [ TaxCharge( tax_class, amount, detail )
                    for tax_class, amount, detail in income_tax_charges if amount > 0 ]
        credits = []
        if premium_credit > 0:
            credits.append(
                TaxCredit(
                    ExpenseTaxClass.ORDINARY_INCOME_TAX, premium_credit,
                    f'ACA premium tax credit at {format_money( figures.aca_magi )} MAGI.' ) )
        income_tax_total = self._net_income_tax( charges, credits )
        worksheet = build_worksheet( TaxYearInputs(
            year                    = fiscal_window.span.end_date.year,
            ordinary_brackets       = self._parameters.ordinary_brackets[ status ],
            ltcg_brackets           = self._parameters.ltcg_brackets[ status ],
            niit_threshold          = niit_threshold,
            income_accounts         = fiscal_window.income_accounts(),
            provisional_income      = self._provisional_income( ss_gross, ss_worksheet_income ),
            ss_gross                = ss_gross,
            taxable_ss              = taxable_ss,
            agi                     = agi,
            taxable_long_term_gains = split.preferential,
            net_investment_income   = net_investment_income,
            standard_deduction      = standard_deduction,
            applied_deduction       = deduction,
            taxable_ordinary_income = split.ordinary,
            taxable_income          = taxable_income,
            niit_magi               = figures.niit_magi,
            ordinary_tax            = income_tax.ordinary,
            capital_gains_tax       = income_tax.capital_gains,
            section_1250_tax        = income_tax.section_1250,
            collectibles_tax        = income_tax.collectibles,
            niit                    = niit,
            state_income_tax        = state_income_tax,
            total_tax               = income_tax_total ) )
        return TaxAssessment(
            charges           = charges,
            credits           = credits,
            closing_tax_state = TaxState(
                capital_loss_carryover = netted.carryover,
                passive_loss_carryover = PassiveLossCarryover( suspended = passive.suspended ),
                prior_year_income_tax  = income_tax_total ),
            figures           = figures,
            worksheet         = worksheet,
        )

    def assess_employment_tax( self, fiscal_window : FiscalWindowView, tax_context : TaxContext ) -> Decimal:
        """Employee FICA on the year-to-date wages in `fiscal_window`, at the year's effective filing
        status (the surtax threshold is status-dependent). Cumulative by construction, so the caller
        pays the increment not yet withheld this year."""
        status = resolve_filing_status(
            tax_context.filing_status, tax_context.spouse_death_year, fiscal_window.span.end_date.year )
        return self._employment_tax( status, fiscal_window )

    @staticmethod
    def _net_income_tax( charges : list, credits : list ) -> Decimal:
        """The net income tax an assessment charges: total charges less refundable credits. The same
        quantity that closes onto `TaxState.prior_year_income_tax` and that the estimate caps against,
        so both read it from here."""
        return ( sum( ( charge.amount for charge in charges ), _ZERO )
                 - sum( ( credit.amount for credit in credits ), _ZERO ) )

    def estimate_income_tax( self, fiscal_window : FiscalWindowView, tax_context : TaxContext,
                             opening_tax_state : Optional[ TaxState ] ) -> Decimal:
        """The safe-harbor estimate to prepay: the lesser of this year's liability so far -- assessed
        on the income recognized before any funding draw (exactly so at annual granularity; see the
        Period's note on the sub-annual case) -- and last year's total tax. A smart planner pays the
        minimum needed to avoid an underpayment penalty and floats the rest (a one-time spike included)
        to the return next year; capping at the actual current liability also means an anomalously high
        prior year never over-charges the year after. With no prior year on file (bootstrapping), the
        current figure is used uncapped."""
        assessment = self.assess( fiscal_window, tax_context, opening_tax_state )
        current = max( _ZERO, self._net_income_tax( assessment.charges, assessment.credits ) )
        prior = opening_tax_state.prior_year_income_tax if isinstance( opening_tax_state, TaxState ) else None
        if prior is None:
            return current
        return min( prior, current )

    def _pretax_holdings( self, fiscal_window : FiscalWindowView,
                          tax_context : TaxContext ) -> Iterator[ tuple[ Account, TaxSubject ] ]:
        """Each pre-tax retirement holding paired with its owner -- the shared subject of the
        early-withdrawal penalty and the RMD. A pre-tax holding without a resolvable owner
        raises: these rules turn on the owner's age, so a missing owner is an error."""
        for holding in fiscal_window.holdings():
            if holding.asset_class != AssetClass.PRETAX_RETIREMENT:
                continue
            owner = tax_context.subject_for( holding.owner_handle )
            if owner is None:
                raise ValueError(
                    f'No owner on file for {holding}; the pre-tax retirement rules need '
                    'the owner age.' )
            yield ( holding, owner )
            continue
        return

    def _pretax_contributions( self, fiscal_window : FiscalWindowView ) -> Decimal:
        """The year's cash contributions into pre-tax retirement holdings -- the above-the-line
        deduction. Read from the books view; the employer match and Roth contributions are
        excluded by construction (only cash into a pre-tax holding counts)."""
        return sum(
            ( fiscal_window.contributions_from_cash( holding )
              for holding in fiscal_window.holdings()
              if holding.asset_class == AssetClass.PRETAX_RETIREMENT ),
            _ZERO )

    def assess_penalties( self, fiscal_window : FiscalWindowView,
                          tax_context : TaxContext ) -> list[ TaxPenalty ]:
        """The early-withdrawal penalties for an owner under 59-1/2. Pre-tax and Roth are computed
        separately because their base differs -- the whole distribution for a pre-tax account (all
        ordinary) versus only the earnings above basis for a Roth (its basis comes out free) -- though
        both are the same 10% rate and penalty class. A missing owner age raises, never a silent
        exemption."""
        return ( self._pretax_early_withdrawal_penalties( fiscal_window, tax_context )
                 + self._roth_early_withdrawal_penalties( fiscal_window, tax_context ) )

    def _pretax_early_withdrawal_penalties( self, fiscal_window : FiscalWindowView,
                                            tax_context : TaxContext ) -> list[ TaxPenalty ]:
        """10% of the year's pre-tax distributions to cash for an owner under 59-1/2. Read from the
        books view -- `distributions_to_cash` already excludes conversions to Roth (which pay no cash)
        -- so any cash distribution, scheduled or a funding draw, is caught."""
        rate      = self._parameters.early_withdrawal_rate
        age_limit = self._parameters.early_withdrawal_age
        penalties = list()
        for holding, owner in self._pretax_holdings( fiscal_window, tax_context ):
            if owner.age >= age_limit:
                continue
            distributed = fiscal_window.distributions_to_cash( holding )
            if distributed <= 0:
                continue
            penalties.append(
                TaxPenalty(
                    tax_class = ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY,
                    amount    = rate * distributed,
                    reason    = f'{rate:.0%} early-withdrawal penalty on {format_money( distributed )} '
                                f'from {holding}.',
                )
            )
            continue
        return penalties

    def _roth_early_earnings_by_owner( self, fiscal_window : FiscalWindowView, tax_context : TaxContext ):
        """Each owner under 59-1/2 paired with the Roth earnings they withdrew this year, for owners with
        positive earnings. The single base the ordinary-income inclusion and the early-withdrawal penalty
        both read, so the taxed amount and the penalized amount are the same figure by construction and
        cannot drift apart. Only the earnings above basis appear (a Roth basis withdrawal is free); the
        earnings of an owner 59-1/2+ are qualified and excluded."""
        age_limit = self._parameters.early_withdrawal_age
        for subject in tax_context.subjects:
            if ( subject.handle is None ) or ( subject.age >= age_limit ):
                continue
            earnings = fiscal_window.income_for_owner( IncomeTaxClass.ROTH_EARNINGS, subject.handle )
            if earnings > 0:
                yield subject, earnings
            continue
        return

    def _roth_early_withdrawal_penalties( self, fiscal_window : FiscalWindowView,
                                          tax_context : TaxContext ) -> list[ TaxPenalty ]:
        """10% of a Roth's withdrawn earnings for an owner under 59-1/2, one penalty per owner. Only the
        earnings above basis are penalized: a Roth basis withdrawal is always free, so the base is the
        owner's Roth Earnings income, not the whole distribution."""
        rate = self._parameters.early_withdrawal_rate
        return [
            TaxPenalty(
                tax_class = ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY,
                amount    = rate * earnings,
                reason    = f'{format_money( earnings )} of Roth earnings withdrawn before 59-1/2: '
                            f'taxed as ordinary income plus a {rate:.0%} early-withdrawal penalty.',
            )
            for _subject, earnings in self._roth_early_earnings_by_owner( fiscal_window, tax_context )
        ]

    def _roth_early_earnings( self, fiscal_window : FiscalWindowView,
                              tax_context : TaxContext ) -> Decimal:
        """The total Roth earnings withdrawn by owners under 59-1/2 -- ordinary income (the earnings of an
        owner 59-1/2+ are tax-free and excluded). The same base the Roth early-withdrawal penalty hits.

        Approximation (deliberate): the qualified test is age alone. The 5-year holding rules (the
        account clock and each conversion's clock) are not modeled -- earnings at 59-1/2+ are treated
        as qualified -- and a conversion is lumped into basis with no 5-year conversion-recapture
        penalty. Withdrawal ordering is basis-first (contributions/conversions), then earnings."""
        return sum(
            ( earnings
              for _subject, earnings in self._roth_early_earnings_by_owner( fiscal_window, tax_context ) ),
            _ZERO )

    def forced_transactions( self, fiscal_window : FiscalWindowView,
                             tax_context : TaxContext ) -> list[ ForcedTransaction ]:
        """The required minimum distributions for this fiscal year: for each pre-tax holding,
        size the RMD on its prior-year-end balance and the owner's age/cohort, then force the
        shortfall not already met by cash distributions this year. A conversion to Roth pays
        no cash, so it does not count -- the RMD must still come out to the taxpayer. Forced per
        account; aggregating a person's IRA RMDs across accounts is not modeled."""
        forced = list()
        for holding, owner in self._pretax_holdings( fiscal_window, tax_context ):
            required = rmd.required_minimum_distribution(
                fiscal_window.opening_value( holding ), owner.age, owner.birth_year )
            shortfall = required - fiscal_window.distributions_to_cash( holding )
            if shortfall <= 0:
                continue
            forced.append(
                ForcedTransaction(
                    account = holding,
                    amount  = shortfall,
                    reason  = f'Required minimum distribution of {format_money( shortfall )} '
                              f'from {holding}.' ) )
            continue
        return forced

    def contribution_limit( self, kind : ContributionKind, age : int ) -> Decimal:
        """The annual employee limit for `kind` at this owner `age`: the base elective-deferral
        (employer plan) or IRA (personal) limit, plus the matching catch-up once the owner reaches
        the catch-up age. An employer match has no kind and is not routed here."""
        limits = self._parameters.contribution_limits
        if kind == ContributionKind.EMPLOYER_PLAN:
            base, catch_up = limits.elective_deferral, limits.elective_deferral_catch_up
        else:
            base, catch_up = limits.ira, limits.ira_catch_up
        bonus = catch_up if age >= limits.catch_up_age else Decimal( '0' )
        return base + bonus

    def _net_capital_gains( self, net_short : Decimal, net_long : Decimal ) -> _NetCapital:
        """Net short-term against long-term per Schedule D. A loss in one character
        first offsets a gain in the other; a surviving net gain keeps the positive
        character; a surviving net loss offsets ordinary income up to the cap
        (short-term first) and carries the rest forward, preserving character."""
        total = net_short + net_long
        if total >= 0:
            if net_short >= 0 and net_long >= 0:
                gain_ordinary, gain_preferential = net_short, net_long
            elif net_short < 0:
                gain_ordinary, gain_preferential = _ZERO, total
            else:
                gain_ordinary, gain_preferential = total, _ZERO
            return _NetCapital( gain_ordinary, gain_preferential, _ZERO, CapitalLossCarryover() )

        loss   = -total
        offset = min( self._parameters.capital_loss_offset_cap, loss )
        if net_short < 0 and net_long < 0:
            short_loss, long_loss = -net_short, -net_long
        elif net_short < 0:
            short_loss, long_loss = loss, _ZERO
        else:
            short_loss, long_loss = _ZERO, loss
        offset_from_short = min( short_loss, offset )
        offset_from_long  = offset - offset_from_short
        carryover = CapitalLossCarryover(
            short = short_loss - offset_from_short,
            long  = long_loss - offset_from_long,
        )
        return _NetCapital( _ZERO, _ZERO, offset, carryover )

    def _split_rental_gain( self, book_gain : Decimal, recapture : Decimal ) -> _RentalGainSplit:
        """Split a rental disposition's gain into its §1250 recapture and long-term remainder.
        `book_gain` is proceeds minus original cost basis (netted across rentals sold this year);
        `recapture` is the accumulated straight-line depreciation. The unrecaptured §1250 gain is the
        recapture capped at the actual total gain (book gain + recapture) -- a rental sold at or below
        its adjusted basis recaptures less, or none -- and the remainder (possibly a long-term loss)
        stays long-term."""
        total_gain   = book_gain + recapture
        section_1250 = min( recapture, max( _ZERO, total_gain ) )
        return _RentalGainSplit( section_1250 = section_1250, long_term = total_gain - section_1250 )

    def _depreciation_recapture( self, tax_context : TaxContext ) -> Decimal:
        """The accumulated straight-line depreciation from the year's rental dispositions (through each
        sale date) -- the raw §1250 recapture, before `_split_rental_gain` caps it at the actual
        gain."""
        recapture = _ZERO
        for tax_property in tax_context.properties:
            disposition = tax_property.disposition
            if disposition is None:
                continue
            if tax_property.holding.asset_class != AssetClass.REAL_ESTATE_RENTAL:
                continue
            recapture += accumulated_depreciation(
                tax_property.depreciable_basis, tax_property.acquisition_date,
                disposition.sale_date, tax_property.property_type )
            continue
        return recapture

    def _rental_net_income( self, fiscal_window : FiscalWindowView, tax_context : TaxContext ) -> Decimal:
        """Net taxable rental income: gross rents minus operating expenses minus
        depreciation (computed per rental from its attributes for the window). It is
        ordinary income and net investment income, and may be negative (a rental loss;
        the passive-activity-loss limits are applied by `_passive_activity_result`)."""
        gross        = fiscal_window.income( IncomeTaxClass.GROSS_RENTAL )
        operating    = fiscal_window.expense( ExpenseTaxClass.RENTAL_EXPENSE )
        depreciation = self._rental_depreciation( fiscal_window.span, tax_context )
        return gross - operating - depreciation

    def _rental_depreciation( self, span : DateSpan, tax_context : TaxContext ) -> Decimal:
        """Total depreciation deductible this window across all rental properties --
        each accrued from acquisition (or the prior close) to the window end, or to the
        sale date if sold mid-year."""
        total = _ZERO
        for tax_property in tax_context.properties:
            if tax_property.holding.asset_class != AssetClass.REAL_ESTATE_RENTAL:
                continue
            disposition = tax_property.disposition
            close = span.end_date
            if disposition is not None and disposition.sale_date < close:
                close = disposition.sale_date
            total += period_depreciation(
                tax_property.depreciable_basis, tax_property.acquisition_date,
                tax_property.property_type, span.day_before_start, close )
            continue
        return total

    def _passive_activity_result(
            self, net_rental : Decimal, phaseout_magi : Decimal,
            prior_suspended : Decimal, tax_context : TaxContext ) -> _PassiveActivity:
        """Apply the passive-activity-loss rules to the year's net rental. Prior
        suspended losses first net against current passive income; a remaining net loss
        is deductible against other income only up to the active-participation allowance
        (phased out over `phaseout_magi`), and the excess is suspended and carried
        forward. Returns the amount flowing into ordinary income / NII and the new
        suspended carryforward.

        On a full disposition of the rental activity (`_rental_activity_fully_disposed`), the
        passive-activity limitation lifts: every suspended (and current-year) loss is deductible
        against any income this year, and nothing carries forward.

        ASSUMPTION: rentals are aggregated and treated as a single activity with uniform
        active participation (`tax_context.rental_active_participation`). Correct for a
        single rental or several uniformly-participated ones; a *mix* of active and passive
        rentals is not supported."""
        combined = net_rental - prior_suspended
        if combined >= _ZERO:
            return _PassiveActivity( deductible = combined, suspended = _ZERO )
        if self._rental_activity_fully_disposed( tax_context ):
            return _PassiveActivity( deductible = combined, suspended = _ZERO )
        loss      = -combined
        allowance = self._passive_loss_allowance( phaseout_magi ) \
            if tax_context.rental_active_participation else _ZERO
        allowed   = min( loss, allowance )
        return _PassiveActivity( deductible = -allowed, suspended = loss - allowed )

    def _rental_activity_fully_disposed( self, tax_context : TaxContext ) -> bool:
        """Whether the aggregate rental activity is fully wound down this fiscal year -- at least one
        rental disposed and none still held. Under the single-aggregate-activity model a *partial*
        disposition (some rentals still held) does not release the suspended losses."""
        rentals = [ tax_property for tax_property in tax_context.properties
                    if tax_property.holding.asset_class == AssetClass.REAL_ESTATE_RENTAL ]
        return bool( rentals ) and all( tax_property.disposition is not None for tax_property in rentals )

    def _passive_loss_allowance( self, magi : Decimal ) -> Decimal:
        """The active-participation special allowance, phased out linearly across the
        MAGI band (full below the start, zero at/above the end)."""
        rules = self._parameters.passive_activity
        if magi <= rules.phaseout_start:
            return rules.loss_allowance
        if magi >= rules.phaseout_end:
            return _ZERO
        band = rules.phaseout_end - rules.phaseout_start
        return rules.loss_allowance * ( rules.phaseout_end - magi ) / band

    def _premium_tax_credit( self, aca_magi : Decimal,
                             enrollment : Optional[ SubsidizedHealthEnrollment ] ) -> Decimal:
        """The ACA premium tax credit: the benchmark plan cost less the household's
        expected contribution -- a share of income that is zero below the lower
        poverty-ratio and rises with the ratio to the cap -- floored at zero, then capped
        at the actual premium paid (the credit cannot exceed what the household spent on its
        plan). Zero when not enrolled, and zero above the eligibility cliff
        (`applicable_upper_ratio`, 400% FPL under reverted post-2025 law). Enrollment-month
        proration, advance-PTC reconciliation, and the under-100%-FPL Medicaid floor are not
        modeled."""
        if enrollment is None:
            return _ZERO
        aca   = self._parameters.aca
        ratio = aca_magi / aca.poverty_line( enrollment.household_size )
        # The eligibility cliff: above the upper poverty-ratio the benefit does not phase out -- it ends.
        if ratio > aca.applicable_upper_ratio:
            return _ZERO
        applicable_rate = max( _ZERO, min(
            aca.applicable_max_rate, aca.applicable_slope * ( ratio - aca.applicable_lower_ratio ) ) )
        expected_contribution = applicable_rate * aca_magi
        credit = max( _ZERO, enrollment.reference_premium - expected_contribution )
        return min( credit, enrollment.actual_premium )

    def _provisional_income( self, ss_gross : Decimal, other_income : Decimal ) -> Decimal:
        """The Social Security provisional-income base: other income (which includes tax-exempt interest,
        counted here though not in AGI) plus half the gross benefits -- what the two-tier inclusion
        worksheet is measured against. Shared by the inclusion calculation and the tax display worksheet."""
        return other_income + ss_gross * _HALF

    def _taxable_social_security(
            self, status : FilingStatus, ss_gross : Decimal, other_income : Decimal ) -> Decimal:
        """The taxable portion of Social Security via the IRS two-tier worksheet:
        nothing below the base threshold, up to 50% between base and additional, up
        to 85% above -- capped at 85% of benefits. `other_income` is the provisional-income
        base (it includes tax-exempt interest, which counts here though not in AGI); the
        worksheet has no inner dependency on the tax being computed."""
        thresholds  = self._parameters.ss_thresholds[ status ]
        provisional = self._provisional_income( ss_gross, other_income )
        if provisional <= thresholds.base:
            return _ZERO
        if provisional <= thresholds.additional:
            return min( ( provisional - thresholds.base ) * _HALF, ss_gross * _HALF )
        lower_tier = min( ss_gross * _HALF, ( thresholds.additional - thresholds.base ) * _HALF )
        upper_tier = ( provisional - thresholds.additional ) * _SS_MAX_RATE
        return min( ss_gross * _SS_MAX_RATE, lower_tier + upper_tier )

    def _standard_deduction( self, status : FilingStatus, tax_context : TaxContext, agi : Decimal ) -> Decimal:
        """Base deduction plus the age-65 and senior bonuses for each subject 65+, with the
        senior bonus phased out linearly across the phase-out band -- keyed on AGI, not the
        senior deduction's own MAGI (a simplification)."""
        standard = self._parameters.standard_deduction[ status ]
        seniors  = tax_context.count_age_at_least( 65 )
        deduction = standard.base + standard.age_65_bonus * seniors
        deduction += standard.senior_bonus * seniors * self._senior_phaseout_factor( standard, agi )
        return deduction

    def _itemized_deduction(
            self, fiscal_window : FiscalWindowView, agi : Decimal, state_income_tax : Decimal ) -> Decimal:
        """Total itemized deductions: medical above the AGI floor, SALT up to its
        cap, mortgage interest, and charitable gifts up to the AGI ceiling. SALT is the
        ledger's state/local taxes (property tax) plus the modeled `state_income_tax`,
        together capped -- the state income tax accrued this year deducts the same year
        (an accrual simplification of cash-basis taxes-paid). The mortgage
        acquisition-debt limit and the charitable carryover of the excess are not modeled."""
        rules   = self._parameters.itemized_rules
        medical = max(
            _ZERO,
            fiscal_window.expense( ExpenseTaxClass.MEDICAL ) - rules.medical_floor_rate * agi )
        salt       = min( fiscal_window.expense( ExpenseTaxClass.SALT ) + state_income_tax, rules.salt_cap )
        mortgage   = fiscal_window.expense( ExpenseTaxClass.MORTGAGE_INTEREST )
        charitable = min( fiscal_window.expense( ExpenseTaxClass.CHARITABLE ),
                          rules.charitable_agi_limit * agi )
        return medical + salt + mortgage + charitable

    def _senior_phaseout_factor( self, standard : StandardDeduction, agi : Decimal ) -> Decimal:
        """The fraction of the senior bonus that survives the AGI phase-out: full
        below the start, zero at/above the end, linear between."""
        if agi <= standard.phaseout_start:
            return Decimal( '1' )
        if agi >= standard.phaseout_end:
            return _ZERO
        band = standard.phaseout_end - standard.phaseout_start
        return ( standard.phaseout_end - agi ) / band

    def _split_taxable_income(
            self, taxable_income : Decimal, preferential : Decimal,
            section_1250 : Decimal, collectibles : Decimal ) -> _TaxableSplit:
        """Apportion taxable income across the rate buckets. Ordinary income sits at
        the bottom; the gains fill the rest. When the deduction eats into gains, the
        preferential bucket is filled first (it survives), then §1250, then
        collectibles -- so the highest-rate gain is reduced first."""
        nonordinary = preferential + section_1250 + collectibles
        ordinary    = max( _ZERO, taxable_income - nonordinary )
        room        = taxable_income - ordinary
        pref_taxed  = min( preferential, room )
        room       -= pref_taxed
        s1250_taxed = min( section_1250, room )
        room       -= s1250_taxed
        coll_taxed  = min( collectibles, room )
        return _TaxableSplit( ordinary, pref_taxed, s1250_taxed, coll_taxed )

    def _tax_on_stack( self, status : FilingStatus, split : _TaxableSplit ) -> _IncomeTaxParts:
        """Tax the apportioned buckets as a stack, in the IRC Schedule D Tax Worksheet order,
        returning each layer's tax separately: ordinary brackets on ordinary income; the 0/15/20%
        preferential gains at the LTCG brackets stacked directly above ordinary income (so they keep
        their low brackets, including 0%); then the §1250 and collectibles gains at ordinary rates
        stacked *above* the preferential gains, each capped at its maximum rate (so a high-income
        year reaches the 25%/28% cap, while a low-income year pays the lower ordinary rate). The
        layers sum to the total income tax."""
        ordinary = self._parameters.ordinary_brackets[ status ]
        ltcg     = self._parameters.ltcg_brackets[ status ]

        ordinary_tax      = ordinary.tax_on( split.ordinary )
        # Preferential long-term gains sit right above ordinary income.
        capital_gains_tax = (
            ltcg.tax_on( split.ordinary + split.preferential ) - ltcg.tax_on( split.ordinary ) )
        # §1250 recapture and collectibles stack above the preferential gains, at ordinary rates
        # capped at their maximum -- so their rate is measured against the high end of the stack.
        base             = split.ordinary + split.preferential
        section_1250_tax = self._capped_gain_tax(
            ordinary, base, split.section_1250, self._parameters.section_1250_rate )
        base += split.section_1250
        collectibles_tax = self._capped_gain_tax(
            ordinary, base, split.collectibles, self._parameters.collectibles_rate )
        return _IncomeTaxParts(
            ordinary = ordinary_tax, capital_gains = capital_gains_tax,
            section_1250 = section_1250_tax, collectibles = collectibles_tax )

    def _capped_gain_tax( self, ordinary : BracketTable, base : Decimal, gain : Decimal, cap : Decimal ) -> Decimal:
        """A maximum-rate gain stacked on `base`: ordinary-rate tax on the gain, but
        never more than the cap rate times the gain."""
        ordinary_rate_tax = ordinary.tax_on( base + gain ) - ordinary.tax_on( base )
        return min( ordinary_rate_tax, cap * gain )

    def _net_investment_income_tax(
            self, status : FilingStatus, magi : Decimal, net_investment_income : Decimal ) -> Decimal:
        """NIIT: the rate applied to the lesser of net investment income and MAGI
        over the filing-status threshold (zero below it). `magi` is the NIIT MAGI
        (`figures.niit_magi` = AGI + the foreign exclusion, which is not modeled -> AGI)."""
        excess = max( _ZERO, magi - self._parameters.niit_thresholds[ status ] )
        return self._parameters.niit_rate * min( net_investment_income, excess )

    def _employment_tax( self, status : FilingStatus, fiscal_window : FiscalWindowView ) -> Decimal:
        """Employee FICA: Social Security on each worker's wages up to the wage base
        (capped per worker, so two earners get two caps), Medicare on all wages, plus
        the Additional Medicare surtax on combined wages over the filing-status
        threshold. Each worker has their own WAGES account, so the per-worker wage
        amounts come straight from the ledger via the fiscal window."""
        rules        = self._parameters.fica_rules
        worker_wages = fiscal_window.income_by_account( IncomeTaxClass.WAGES )
        total_wages  = sum( worker_wages, _ZERO )
        social_security = sum(
            ( rules.ss_rate * min( wages, rules.ss_wage_base ) for wages in worker_wages ), _ZERO )
        medicare = rules.medicare_rate * total_wages
        surtax   = rules.additional_medicare_rate * max(
            _ZERO, total_wages - rules.additional_medicare_thresholds[ status ] )
        return social_security + medicare + surtax

    def _state_income_tax_charge(
            self, fiscal_window : FiscalWindowView, agi : Decimal, taxable_ss : Decimal ) -> Decimal:
        """The simplified state income tax: the flat rate on federal AGI, less the state's exemption of
        retirement income -- a share of taxable Social Security and of pension + pre-tax
        retirement-distribution income (most states exempt Social Security, and several exempt pensions
        and retirement-account withdrawals). Reads AGI; its result joins the federal SALT deduction,
        but nothing feeds back to it."""
        policy     = self._state_income_tax
        retirement = ( fiscal_window.income( IncomeTaxClass.PENSION )
                       + fiscal_window.income( IncomeTaxClass.RETIREMENT_DISTRIBUTION ) )
        exempt     = policy.social_security_exempt * taxable_ss + policy.retirement_exempt * retirement
        return policy.rate.change_on( max( _ZERO, agi - exempt ) )
