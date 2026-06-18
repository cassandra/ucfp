"""The US federal income-tax engine.

`USFederalTaxEngine` replaces `ZeroTaxEngine` with the real federal pipeline: an
ordered DAG over a fiscal year's income that yields the tax charges. The engine owns
the *structure* (the stages and their dependencies); the projectable *values* for
the year are the `TaxParameters` it is constructed with, so the Scenario builds one
engine per projected year (indexing the baseline for inflation, or applying a
what-if such as a rate hike).

Pipeline (strict DAG): capital-gains netting (short vs long, with the prior year's
loss carryover applied first, character-preserving) -> Social-Security taxability
worksheet -> AGI -> the greater of the standard and itemized deductions -> split
taxable income across rate buckets -> tax on the stack -> the 3.8% net investment
income tax (NIIT) -> employee FICA on wages -> total -> charges, plus the loss
carryover to thread forward.

The stack, bottom to top: ordinary income at ordinary brackets; then the §1250 (25%)
and collectibles (28%) maximum-rate long-term gains, each taxed at ordinary rates
stacked on ordinary income but capped at its maximum rate; then the 0/15/20%
preferential gains (qualified dividends + regular long-term gains) at the LTCG
brackets stacked on top of everything ordinary-rated. Stacking via
`table.tax_on(base + bucket) - table.tax_on(base)` spans rate boundaries correctly.

DEFERRED (added as later stages land, none of which change this contract): cross-
category capital-loss absorption (a net loss should reduce 28% then 25% then 0/15/20%
gains -- the §1250/collectibles buckets are not yet in the ST/LT netting, only their
gains are taxed); MAGI distinct from AGI (the foreign-earned-income add-back for
NIIT, the tax-exempt-interest / untaxed-SS add-backs for ACA); the mortgage
acquisition-debt limit and the charitable 5-year carryover; the ACA premium tax
credit; rental income (gross netted with expenses), which also belongs in net
investment income. Until then, AGI stands in for MAGI.
"""
from decimal import Decimal
from typing import NamedTuple

from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass
from ucfp.tax.engine import TaxAssessment, TaxEngine

from .context import TaxContext
from .parameters import TaxParameters
from .state import CapitalLossCarryover, TaxState

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


class USFederalTaxEngine( TaxEngine ):
    """Assesses US federal income tax for one fiscal year against the parameters it
    is constructed with."""

    def __init__( self, parameters : TaxParameters ):
        self._parameters = parameters

    def assess( self, fiscal_window, tax_context : TaxContext, opening_tax_state ) -> TaxAssessment:
        status    = tax_context.filing_status
        carryover = ( opening_tax_state or TaxState() ).capital_loss_carryover

        wages               = fiscal_window.income( IncomeTaxClass.WAGES )
        ordinary_other      = fiscal_window.income( IncomeTaxClass.ORDINARY )
        taxable_interest    = fiscal_window.income( IncomeTaxClass.TAXABLE_INTEREST )
        qualified_dividends = fiscal_window.income( IncomeTaxClass.QUALIFIED_DIVIDENDS )
        ss_gross            = fiscal_window.income( IncomeTaxClass.SOCIAL_SECURITY )

        net_short = fiscal_window.income( IncomeTaxClass.SHORT_TERM_GAINS ) - carryover.short
        net_long  = fiscal_window.income( IncomeTaxClass.LONG_TERM_GAINS )  - carryover.long
        netted    = self._net_capital_gains( net_short, net_long )

        # The maximum-rate long-term gains have their own buckets; they are not yet
        # part of the ST/LT loss netting (cross-category loss absorption deferred).
        section_1250 = max( _ZERO, fiscal_window.income( IncomeTaxClass.SECTION_1250_GAIN ) )
        collectibles = max( _ZERO, fiscal_window.income( IncomeTaxClass.COLLECTIBLES_GAINS ) )

        ordinary_income     = ( wages + ordinary_other + taxable_interest
                                + netted.gain_ordinary - netted.ordinary_offset )
        preferential_income = qualified_dividends + netted.gain_preferential
        total_gains         = preferential_income + section_1250 + collectibles

        taxable_ss = self._taxable_social_security(
            status, ss_gross, ordinary_income + total_gains )
        agi        = ordinary_income + total_gains + taxable_ss
        deduction  = max(
            self._standard_deduction( status, tax_context, agi ),
            self._itemized_deduction( fiscal_window, agi ) )

        taxable_income = max( _ZERO, agi - deduction )
        split          = self._split_taxable_income(
            taxable_income, preferential_income, section_1250, collectibles )
        income_tax     = self._tax_on_stack( status, split )

        net_investment_income = max(
            _ZERO,
            taxable_interest + qualified_dividends + netted.gain_ordinary
            + netted.gain_preferential + section_1250 + collectibles )
        niit = self._net_investment_income_tax( status, agi, net_investment_income )

        payroll_tax = self._payroll_tax( status, fiscal_window )

        charges = [ ( ExpenseTaxClass.INCOME_TAX, income_tax ) ]
        if payroll_tax > 0:
            charges.append( ( ExpenseTaxClass.PAYROLL_TAX, payroll_tax ) )
        if niit > 0:
            charges.append( ( ExpenseTaxClass.NIIT, niit ) )
        return TaxAssessment(
            charges           = charges,
            closing_tax_state = TaxState( capital_loss_carryover = netted.carryover ),
        )

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

    def _taxable_social_security(
            self, status, ss_gross : Decimal, other_income : Decimal ) -> Decimal:
        """The taxable portion of Social Security via the IRS two-tier worksheet:
        nothing below the base threshold, up to 50% between base and additional, up
        to 85% above -- capped at 85% of benefits. Uses gross benefits and other
        income directly (no inner dependency on the tax being computed)."""
        thresholds  = self._parameters.ss_thresholds[ status ]
        provisional = other_income + ss_gross * _HALF
        if provisional <= thresholds.base:
            return _ZERO
        if provisional <= thresholds.additional:
            return min( ( provisional - thresholds.base ) * _HALF, ss_gross * _HALF )
        lower_tier = min( ss_gross * _HALF, ( thresholds.additional - thresholds.base ) * _HALF )
        upper_tier = ( provisional - thresholds.additional ) * _SS_MAX_RATE
        return min( ss_gross * _SS_MAX_RATE, lower_tier + upper_tier )

    def _standard_deduction( self, status, tax_context : TaxContext, agi : Decimal ) -> Decimal:
        """Base deduction plus the age-65 and senior bonuses for each subject 65+,
        with the senior bonus phased out linearly across the AGI phase-out band."""
        standard = self._parameters.standard_deduction[ status ]
        seniors  = tax_context.count_age_at_least( 65 )
        deduction = standard.base + standard.age_65_bonus * seniors
        deduction += standard.senior_bonus * seniors * self._senior_phaseout_factor( standard, agi )
        return deduction

    def _itemized_deduction( self, fiscal_window, agi : Decimal ) -> Decimal:
        """Total itemized deductions: medical above the AGI floor, SALT up to its
        cap, mortgage interest, and charitable gifts up to the AGI ceiling. The
        mortgage acquisition-debt limit and the charitable 5-year carryover of the
        excess are deferred (rare for the planning cases, and the carryover would
        join TaxState)."""
        rules   = self._parameters.itemized_rules
        medical = max(
            _ZERO,
            fiscal_window.expense( ExpenseTaxClass.MEDICAL ) - rules.medical_floor_rate * agi )
        salt       = min( fiscal_window.expense( ExpenseTaxClass.SALT ), rules.salt_cap )
        mortgage   = fiscal_window.expense( ExpenseTaxClass.MORTGAGE_INTEREST )
        charitable = min( fiscal_window.expense( ExpenseTaxClass.CHARITABLE ),
                          rules.charitable_agi_limit * agi )
        return medical + salt + mortgage + charitable

    def _senior_phaseout_factor( self, standard, agi : Decimal ) -> Decimal:
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

    def _tax_on_stack( self, status, split : _TaxableSplit ) -> Decimal:
        """Tax the apportioned buckets as a stack: ordinary brackets on ordinary
        income; the §1250 and collectibles gains at ordinary rates stacked on top,
        each capped at its maximum rate; the 0/15/20% preferential gains at the LTCG
        brackets stacked above all ordinary-rated income."""
        ordinary = self._parameters.ordinary_brackets[ status ]
        ltcg     = self._parameters.ltcg_brackets[ status ]

        tax  = ordinary.tax_on( split.ordinary )
        base = split.ordinary
        tax += self._capped_gain_tax(
            ordinary, base, split.section_1250, self._parameters.section_1250_rate )
        base += split.section_1250
        tax += self._capped_gain_tax(
            ordinary, base, split.collectibles, self._parameters.collectibles_rate )
        base += split.collectibles
        tax += ltcg.tax_on( base + split.preferential ) - ltcg.tax_on( base )
        return tax

    def _capped_gain_tax( self, ordinary, base : Decimal, gain : Decimal, cap : Decimal ) -> Decimal:
        """A maximum-rate gain stacked on `base`: ordinary-rate tax on the gain, but
        never more than the cap rate times the gain."""
        ordinary_rate_tax = ordinary.tax_on( base + gain ) - ordinary.tax_on( base )
        return min( ordinary_rate_tax, cap * gain )

    def _net_investment_income_tax(
            self, status, magi : Decimal, net_investment_income : Decimal ) -> Decimal:
        """NIIT: the rate applied to the lesser of net investment income and MAGI
        over the filing-status threshold (zero below it). MAGI = AGI here; the
        foreign-earned-income add-back is deferred."""
        excess = max( _ZERO, magi - self._parameters.niit_thresholds[ status ] )
        return self._parameters.niit_rate * min( net_investment_income, excess )

    def _payroll_tax( self, status, fiscal_window ) -> Decimal:
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
