"""The US federal income-tax engine.

`USFederalTaxEngine` replaces `ZeroTaxEngine` with the real federal pipeline: an
ordered DAG over a fiscal year's income that yields the income-tax charge. The
engine owns the *structure* (the stages and their dependencies); the projectable
*values* for the year are the `TaxParameters` it is constructed with, so the
Scenario builds one engine per projected year (indexing the baseline for inflation,
or applying a what-if such as a rate hike).

Pipeline (strict DAG): Social-Security taxability worksheet -> AGI -> standard
deduction -> split taxable income into ordinary vs preferential -> ordinary brackets
with the preferential (qualified-dividend / long-term-gain) amount stacked on top
-> total -> charge. The preferential stack is `ltcg.tax_on(ordinary + preferential)
- ltcg.tax_on(ordinary)`, which spans LTCG rate boundaries correctly.

DEFERRED (added as later stages land, none of which change this contract):
capital-gains netting and loss carryover; the 25% (§1250) and 28% (collectibles)
special rates; MAGI distinct from AGI (tax-exempt-interest / foreign add-backs);
itemized deductions; NIIT and FICA surtaxes; the ACA premium tax credit. Until
then, short-term gains are taxed as ordinary, AGI stands in for MAGI, and the
deduction is the standard deduction.
"""
from decimal import Decimal

from ucfp.accounts.enums import ExpenseTaxClass, IncomeTaxClass
from ucfp.tax.engine import TaxAssessment, TaxEngine

from .context import TaxContext
from .parameters import TaxParameters

# Income tax-classes taxed at ordinary rates, and at preferential (capital-gains)
# rates. Social Security is handled separately (its taxable portion is computed by
# the worksheet); tax-free and tax-exempt classes contribute nothing here.
_ORDINARY_CLASSES = (
    IncomeTaxClass.WAGES,
    IncomeTaxClass.ORDINARY,
    IncomeTaxClass.SHORT_TERM_GAINS,
)
_PREFERENTIAL_CLASSES = (
    IncomeTaxClass.QUALIFIED_DIVIDENDS,
    IncomeTaxClass.LONG_TERM_GAINS,
)

_HALF        = Decimal( '0.5' )
_SS_MAX_RATE = Decimal( '0.85' )


class USFederalTaxEngine( TaxEngine ):
    """Assesses US federal income tax for one fiscal year against the parameters it
    is constructed with."""

    def __init__( self, parameters : TaxParameters ):
        self._parameters = parameters

    def assess( self, fiscal_window, tax_context : TaxContext, opening_attrs ) -> TaxAssessment:
        status = tax_context.filing_status

        ordinary_income     = sum(
            ( fiscal_window.income( c ) for c in _ORDINARY_CLASSES ), Decimal( '0' ) )
        preferential_income = sum(
            ( fiscal_window.income( c ) for c in _PREFERENTIAL_CLASSES ), Decimal( '0' ) )
        ss_gross            = fiscal_window.income( IncomeTaxClass.SOCIAL_SECURITY )

        taxable_ss = self._taxable_social_security(
            status, ss_gross, ordinary_income + preferential_income )
        agi        = ordinary_income + preferential_income + taxable_ss
        deduction  = self._standard_deduction( status, tax_context, agi )

        taxable_income      = max( Decimal( '0' ), agi - deduction )
        preferential_taxed  = min( preferential_income, taxable_income )
        ordinary_taxed      = taxable_income - preferential_taxed

        ordinary_tax     = self._parameters.ordinary_brackets[ status ].tax_on( ordinary_taxed )
        preferential_tax = self._preferential_tax( status, ordinary_taxed, preferential_taxed )

        total = ordinary_tax + preferential_tax
        return TaxAssessment( charges = [ ( ExpenseTaxClass.INCOME_TAX, total ) ] )

    def _taxable_social_security(
            self, status, ss_gross : Decimal, other_income : Decimal ) -> Decimal:
        """The taxable portion of Social Security via the IRS two-tier worksheet:
        nothing below the base threshold, up to 50% between base and additional, up
        to 85% above -- capped at 85% of benefits. Uses gross benefits and other
        income directly (no inner dependency on the tax being computed)."""
        thresholds  = self._parameters.ss_thresholds[ status ]
        provisional = other_income + ss_gross * _HALF
        if provisional <= thresholds.base:
            return Decimal( '0' )
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
            return Decimal( '0' )
        band = standard.phaseout_end - standard.phaseout_start
        return ( standard.phaseout_end - agi ) / band

    def _preferential_tax(
            self, status, ordinary_taxed : Decimal, preferential_taxed : Decimal ) -> Decimal:
        """Tax on preferential income stacked on top of ordinary income: the LTCG
        tax on the combined stack less the LTCG tax on the ordinary base, so the
        preferential amount is rated by the brackets it actually lands in."""
        ltcg = self._parameters.ltcg_brackets[ status ]
        return ltcg.tax_on( ordinary_taxed + preferential_taxed ) - ltcg.tax_on( ordinary_taxed )
