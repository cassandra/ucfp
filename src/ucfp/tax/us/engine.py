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
worksheet -> AGI -> the greater of the standard and itemized deductions -> split
taxable income across rate buckets -> tax on the stack -> the 3.8% net investment
income tax (NIIT, on its own MAGI) -> employee FICA on wages -> the ACA premium tax
credit (a refundable credit, on its own MAGI) -> total -> charges + credits, plus the
loss carryover to thread forward. AGI and the modified-AGI variants are surfaced as
`TaxFigures` on the assessment (see `figures.py`); NIIT uses `niit_magi`, the PTC uses
`aca_magi`, and `irmaa_magi` is ready for the Scenario's IRMAA.

The stack, bottom to top: ordinary income at ordinary brackets; then the §1250 (25%)
and collectibles (28%) maximum-rate long-term gains, each taxed at ordinary rates
stacked on ordinary income but capped at its maximum rate; then the 0/15/20%
preferential gains (qualified dividends + regular long-term gains) at the LTCG
brackets stacked on top of everything ordinary-rated. Stacking via
`table.tax_on(base + bucket) - table.tax_on(base)` spans rate boundaries correctly.

Net rental income (gross rents minus operating expenses minus depreciation computed
from each rental's attributes) is ordinary income and net investment income; it may be
negative (a rental loss).

DEFERRED (added as later stages land, none of which change this contract): cross-
category capital-loss absorption (a net loss should reduce 28% then 25% then 0/15/20%
gains -- the §1250/collectibles buckets are not yet in the ST/LT netting, only their
gains are taxed); passive-activity-loss limits on rental losses; the foreign-earned-
income exclusion add-back (a MAGI component, not modeled → zero); the mortgage
acquisition-debt limit and the charitable 5-year carryover; ACA refinements (advance-
PTC reconciliation, enrollment-month proration, the actual-premium cap, the
under-100%-FPL Medicaid floor).
"""
from decimal import Decimal
from typing import NamedTuple

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.tax.engine import TaxAssessment, TaxCharge, TaxCredit, TaxEngine

from .context import TaxContext
from .depreciation import accumulated_depreciation, period_depreciation
from .figures import TaxFigures
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


class _PropertySaleAdjustments( NamedTuple ):
    """The gain adjustments from a year's property sales: the §121 residence-gain
    exclusion (reduces long-term gains) and the §1250 depreciation recapture (adds to
    the 25% bucket)."""

    residence_exclusion    : Decimal
    depreciation_recapture : Decimal


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
        tax_exempt_interest = fiscal_window.income( IncomeTaxClass.TAX_EXEMPT_INTEREST )
        qualified_dividends = fiscal_window.income( IncomeTaxClass.QUALIFIED_DIVIDENDS )
        ss_gross            = fiscal_window.income( IncomeTaxClass.SOCIAL_SECURITY )

        # Property sales adjust the gains the ledger posted: §121 excludes residence
        # gain from long-term gains; §1250 adds rental depreciation recapture to the
        # 25% bucket (the book gain stays in long-term gains).
        sales = self._property_sale_adjustments( tax_context, status )
        long_term_gains   = fiscal_window.income( IncomeTaxClass.LONG_TERM_GAINS ) - sales.residence_exclusion
        section_1250_gain = (
            fiscal_window.income( IncomeTaxClass.SECTION_1250_GAIN ) + sales.depreciation_recapture )

        net_short = fiscal_window.income( IncomeTaxClass.SHORT_TERM_GAINS ) - carryover.short
        net_long  = long_term_gains - carryover.long
        netted    = self._net_capital_gains( net_short, net_long )

        # The maximum-rate long-term gains have their own buckets; they are not yet
        # part of the ST/LT loss netting (cross-category loss absorption deferred).
        section_1250 = max( _ZERO, section_1250_gain )
        collectibles = max( _ZERO, fiscal_window.income( IncomeTaxClass.COLLECTIBLES_GAINS ) )

        net_rental = self._rental_net_income( fiscal_window, tax_context )

        ordinary_income     = ( wages + ordinary_other + taxable_interest + net_rental
                                + netted.gain_ordinary - netted.ordinary_offset )
        preferential_income = qualified_dividends + netted.gain_preferential
        total_gains         = preferential_income + section_1250 + collectibles

        taxable_ss = self._taxable_social_security(
            status, ss_gross, ordinary_income + total_gains )
        agi        = ordinary_income + total_gains + taxable_ss
        figures    = TaxFigures(
            agi                     = agi,
            tax_exempt_interest     = tax_exempt_interest,
            untaxed_social_security = ss_gross - taxable_ss,
        )
        deduction  = max(
            self._standard_deduction( status, tax_context, agi ),
            self._itemized_deduction( fiscal_window, agi ) )

        taxable_income = max( _ZERO, agi - deduction )
        split          = self._split_taxable_income(
            taxable_income, preferential_income, section_1250, collectibles )
        income_tax     = self._tax_on_stack( status, split )

        net_investment_income = max(
            _ZERO,
            taxable_interest + qualified_dividends + net_rental + netted.gain_ordinary
            + netted.gain_preferential + section_1250 + collectibles )
        niit = self._net_investment_income_tax(
            status, figures.niit_magi, net_investment_income )

        payroll_tax = self._payroll_tax( status, fiscal_window )
        premium_credit = self._premium_tax_credit( figures.aca_magi, tax_context.aca )

        charges = [ TaxCharge( ExpenseTaxClass.INCOME_TAX, income_tax ) ]
        if payroll_tax > 0:
            charges.append( TaxCharge( ExpenseTaxClass.PAYROLL_TAX, payroll_tax ) )
        if niit > 0:
            charges.append( TaxCharge( ExpenseTaxClass.NIIT, niit ) )
        credits = []
        if premium_credit > 0:
            credits.append( TaxCredit( ExpenseTaxClass.INCOME_TAX, premium_credit ) )
        return TaxAssessment(
            charges           = charges,
            credits           = credits,
            closing_tax_state = TaxState( capital_loss_carryover = netted.carryover ),
            figures           = figures,
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

    def _property_sale_adjustments(
            self, tax_context : TaxContext, status ) -> _PropertySaleAdjustments:
        """From the year's property dispositions: the total §121 residence-gain
        exclusion (reduces long-term gains) and the total §1250 depreciation recapture
        (adds to the 25% bucket). Recapture = min(accumulated depreciation, the total
        tax gain = book gain + accumulated depreciation); for a non-negative book gain
        that is the full accumulated depreciation, with the book gain remaining
        long-term. The sale-below-adjusted-basis edge is deferred."""
        exclusion = _ZERO
        recapture = _ZERO
        for tax_property in tax_context.properties:
            disposition = tax_property.disposition
            if disposition is None:
                continue
            asset_class = tax_property.holding.asset_class
            if asset_class == AssetClass.REAL_ESTATE_RESIDENCE:
                cap = self._parameters.section_121_exclusion[ status ]
                exclusion += min( cap, max( _ZERO, disposition.book_gain ) )
            elif asset_class == AssetClass.REAL_ESTATE_RENTAL:
                accumulated = accumulated_depreciation(
                    tax_property.depreciable_basis, tax_property.acquisition_date,
                    disposition.sale_date, tax_property.property_type )
                recapture += min(
                    accumulated, max( _ZERO, disposition.book_gain + accumulated ) )
            continue
        return _PropertySaleAdjustments( exclusion, recapture )

    def _rental_net_income( self, fiscal_window, tax_context : TaxContext ) -> Decimal:
        """Net taxable rental income: gross rents minus operating expenses minus
        depreciation (computed per rental from its attributes for the window). It is
        ordinary income and net investment income, and may be negative (a rental loss);
        passive-activity-loss limits on such losses are deferred."""
        gross        = fiscal_window.income( IncomeTaxClass.GROSS_RENTAL )
        operating    = fiscal_window.expense( ExpenseTaxClass.RENTAL_EXPENSE )
        depreciation = self._rental_depreciation( fiscal_window.span, tax_context )
        return gross - operating - depreciation

    def _rental_depreciation( self, span, tax_context : TaxContext ) -> Decimal:
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

    def _premium_tax_credit( self, aca_magi : Decimal, aca_enrollment ) -> Decimal:
        """The ACA premium tax credit: the benchmark plan cost less the household's
        expected contribution -- a share of income that is zero below the lower
        poverty-ratio and rises with the ratio to the cap -- floored at zero. Zero when
        not enrolled. Enrollment-month proration, advance-PTC reconciliation, the
        actual-premium cap, and the under-100%-FPL Medicaid floor are deferred."""
        if aca_enrollment is None:
            return _ZERO
        aca   = self._parameters.aca
        ratio = aca_magi / aca.poverty_line( aca_enrollment.household_size )
        applicable_rate = max( _ZERO, min(
            aca.applicable_max_rate, aca.applicable_slope * ( ratio - aca.applicable_lower_ratio ) ) )
        expected_contribution = applicable_rate * aca_magi
        return max( _ZERO, aca_enrollment.benchmark_premium - expected_contribution )

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
        over the filing-status threshold (zero below it). `magi` is the NIIT MAGI
        (`figures.niit_magi` = AGI + the foreign exclusion, which is not modeled → AGI)."""
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
