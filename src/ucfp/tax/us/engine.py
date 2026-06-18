"""The US federal income-tax engine.

`USFederalTaxEngine` replaces `ZeroTaxEngine` with the real federal pipeline: an
ordered DAG over a fiscal year's income that yields the income-tax charge. The
engine owns the *structure* (the stages and their dependencies); the projectable
*values* for the year are the `TaxParameters` it is constructed with, so the
Scenario builds one engine per projected year (indexing the baseline for inflation,
or applying a what-if such as a rate hike).

Pipeline (strict DAG): capital-gains netting (short vs long, with the prior year's
loss carryover applied first, character-preserving) -> Social-Security taxability
worksheet -> AGI -> standard deduction -> split taxable income into ordinary vs
preferential -> ordinary brackets with the preferential (qualified-dividend /
long-term-gain) amount stacked on top -> total -> charge, plus the loss carryover to
thread forward. The preferential stack is `ltcg.tax_on(ordinary + preferential) -
ltcg.tax_on(ordinary)`, which spans LTCG rate boundaries correctly.

DEFERRED (added as later stages land, none of which change this contract): the 25%
(§1250) and 28% (collectibles) special rates; MAGI distinct from AGI (tax-exempt-
interest / foreign add-backs); itemized deductions; NIIT and FICA surtaxes; the ACA
premium tax credit. Until then, AGI stands in for MAGI and the deduction is the
standard deduction.
"""
from decimal import Decimal
from typing import NamedTuple

from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass
from ucfp.tax.engine import TaxAssessment, TaxEngine

from .context import TaxContext
from .parameters import TaxParameters
from .state import CapitalLossCarryover, TaxState

# Income tax-classes taxed at flat ordinary rates (capital gains are netted
# separately; Social Security runs through its own worksheet; tax-free and
# tax-exempt classes contribute nothing here).
_ORDINARY_INCOME_CLASSES = ( IncomeTaxClass.WAGES, IncomeTaxClass.ORDINARY )

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


class USFederalTaxEngine( TaxEngine ):
    """Assesses US federal income tax for one fiscal year against the parameters it
    is constructed with."""

    def __init__( self, parameters : TaxParameters ):
        self._parameters = parameters

    def assess( self, fiscal_window, tax_context : TaxContext, opening_tax_state ) -> TaxAssessment:
        status    = tax_context.filing_status
        carryover = ( opening_tax_state or TaxState() ).capital_loss_carryover

        ordinary_base       = sum(
            ( fiscal_window.income( c ) for c in _ORDINARY_INCOME_CLASSES ), _ZERO )
        qualified_dividends = fiscal_window.income( IncomeTaxClass.QUALIFIED_DIVIDENDS )
        ss_gross            = fiscal_window.income( IncomeTaxClass.SOCIAL_SECURITY )

        net_short = fiscal_window.income( IncomeTaxClass.SHORT_TERM_GAINS ) - carryover.short
        net_long  = fiscal_window.income( IncomeTaxClass.LONG_TERM_GAINS )  - carryover.long
        netted    = self._net_capital_gains( net_short, net_long )

        ordinary_income     = ordinary_base + netted.gain_ordinary - netted.ordinary_offset
        preferential_income = qualified_dividends + netted.gain_preferential

        taxable_ss = self._taxable_social_security(
            status, ss_gross, ordinary_income + preferential_income )
        agi        = ordinary_income + preferential_income + taxable_ss
        deduction  = self._standard_deduction( status, tax_context, agi )

        taxable_income     = max( _ZERO, agi - deduction )
        preferential_taxed = min( preferential_income, taxable_income )
        ordinary_taxed     = taxable_income - preferential_taxed

        ordinary_tax     = self._parameters.ordinary_brackets[ status ].tax_on( ordinary_taxed )
        preferential_tax = self._preferential_tax( status, ordinary_taxed, preferential_taxed )

        total = ordinary_tax + preferential_tax
        return TaxAssessment(
            charges           = [ ( ExpenseTaxClass.INCOME_TAX, total ) ],
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

    def _senior_phaseout_factor( self, standard, agi : Decimal ) -> Decimal:
        """The fraction of the senior bonus that survives the AGI phase-out: full
        below the start, zero at/above the end, linear between."""
        if agi <= standard.phaseout_start:
            return Decimal( '1' )
        if agi >= standard.phaseout_end:
            return _ZERO
        band = standard.phaseout_end - standard.phaseout_start
        return ( standard.phaseout_end - agi ) / band

    def _preferential_tax(
            self, status, ordinary_taxed : Decimal, preferential_taxed : Decimal ) -> Decimal:
        """Tax on preferential income stacked on top of ordinary income: the LTCG
        tax on the combined stack less the LTCG tax on the ordinary base, so the
        preferential amount is rated by the brackets it actually lands in."""
        ltcg = self._parameters.ltcg_brackets[ status ]
        return ltcg.tax_on( ordinary_taxed + preferential_taxed ) - ltcg.tax_on( ordinary_taxed )
