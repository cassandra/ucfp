"""The Economic Outlook: the global VALUE-axis assumptions a Forecast projects under.

An outlook is a **schedule** -- a list of `EconomicParameters` segments, each carrying its
own `[start, end]` window like the other time-bound inputs. A run with one set of rates for
the whole horizon is just a single unbounded segment (`EconomicOutlook.constant`); pinning
different rates to different year ranges is more segments.

The Forecast resolves the segment in effect for each interval (by the interval's start
date) into that period's `AssetRates`, so the Period's growth and distribution steps fire.

Segments are resolved at period boundaries (no sub-period rate changes).
"""
from dataclasses import dataclass
from datetime import date

from common.date_window import DateWindow
from common.rate import FULL_RATE, ZERO_RATE, Rate
from common.schedule import Schedule
from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.period.parameters import AssetRates


@dataclass( frozen = True )
class EconomicParameters:
    """The economic rates in effect over a `window`. Holds inflation and the per-asset-class
    appreciation (growth) and yield (distribution) rates in the spreadsheet's vocabulary;
    `asset_rates` maps them to the Period's per-`AssetClass` rates. The window rides here --
    like the other time-bound inputs -- so an `EconomicOutlook` is just a list of these."""

    window                       : DateWindow = DateWindow()
    inflation                    : Rate = ZERO_RATE   # general expense inflation
    medical_inflation            : Rate = ZERO_RATE   # MEDICAL-class expense inflation
    savings_interest             : Rate = ZERO_RATE   # CASH yield (distribution)
    cd_interest                  : Rate = ZERO_RATE   # CDS yield
    bond_appreciation            : Rate = ZERO_RATE   # BONDS price growth
    bond_interest                : Rate = ZERO_RATE   # BONDS coupon (distribution)
    stock_appreciation           : Rate = ZERO_RATE   # STOCKS + DIVIDEND_STOCKS growth
    stock_dividend               : Rate = ZERO_RATE   # DIVIDEND_STOCKS yield
    real_estate_appreciation     : Rate = ZERO_RATE   # residence + rental growth
    precious_metals_appreciation : Rate = ZERO_RATE   # PRECIOUS_METALS growth
    collectibles_appreciation    : Rate = ZERO_RATE   # COLLECTIBLES growth
    depreciation_rate            : Rate = ZERO_RATE   # DEPRECIATING decline (positive = % lost/yr)
    retirement_growth            : Rate = ZERO_RATE   # PRETAX_RETIREMENT + ROTH (blended)
    wage_growth                  : Rate = ZERO_RATE   # WAGES streams
    social_security_cola         : Rate = ZERO_RATE   # SOCIAL_SECURITY streams
    pension_cola                 : Rate = ZERO_RATE   # PENSION streams
    rental_increase              : Rate = ZERO_RATE   # GROSS_RENTAL streams
    # A funding-shortfall assumption (the "2032 cliff"): the retained share of scheduled Social Security
    # benefits payable from `social_security_reduction_year` on (100% = no reduction, the default). Applied
    # as a today's-dollars step on the realized benefit schedule in the planning layer, before tax and
    # composing with the COLA above -- NOT a growth rate, so it is absent from `income_growth_rate`.
    social_security_benefits_payable : Rate = FULL_RATE
    social_security_reduction_year   : int  = 2032

    def asset_rates( self ) -> AssetRates:
        """Resolve into the Period's per-`AssetClass` growth and distribution rates. A class
        absent from a map carries a zero rate (the `AssetRates` default) -- cash and CDs are
        face-value, so they have only a yield, no growth."""
        growth = {
            AssetClass.STOCKS            : self.stock_appreciation,
            AssetClass.DIVIDEND_STOCKS   : self.stock_appreciation,
            AssetClass.BONDS             : self.bond_appreciation,
            AssetClass.PRECIOUS_METALS   : self.precious_metals_appreciation,
            AssetClass.COLLECTIBLES      : self.collectibles_appreciation,
            AssetClass.DEPRECIATING      : self.depreciation_rate.negated(),
            AssetClass.PRETAX_RETIREMENT : self.retirement_growth,
            AssetClass.ROTH              : self.retirement_growth,
            # Every real-estate class (residence, second home, rental) appreciates at the shared rate.
            ** { asset_class : self.real_estate_appreciation
                 for asset_class in AssetClass if asset_class.is_real_estate },
        }
        distribution = {
            AssetClass.CASH            : self.savings_interest,
            AssetClass.CDS             : self.cd_interest,
            AssetClass.BONDS           : self.bond_interest,
            AssetClass.DIVIDEND_STOCKS : self.stock_dividend,
        }
        return AssetRates( growth = growth, distribution = distribution )

    def income_growth_rate( self, income_tax_class : IncomeTaxClass ) -> Rate:
        """The annual growth (COLA) rate for an income class's streams; flat for classes
        with no stream growth (investment income is asset-driven, not grown here)."""
        return {
            IncomeTaxClass.WAGES           : self.wage_growth,
            IncomeTaxClass.SOCIAL_SECURITY : self.social_security_cola,
            IncomeTaxClass.PENSION         : self.pension_cola,
            # Generic ordinary income (other income, taxable receipts) tracks general inflation, distinct
            # from the pension COLA that PENSION now carries.
            IncomeTaxClass.ORDINARY        : self.inflation,
            IncomeTaxClass.GROSS_RENTAL    : self.rental_increase,
        }.get( income_tax_class, ZERO_RATE )

    def expense_inflation_rate( self, expense_tax_class : ExpenseTaxClass ) -> Rate:
        """The annual inflation rate for an expense class: medical for `MEDICAL`, the
        general rate otherwise."""
        if expense_tax_class == ExpenseTaxClass.MEDICAL:
            return self.medical_inflation
        return self.inflation


# Flat (all-zero, unbounded) parameters: the fallback where no segment covers a date.
_FLAT_PARAMETERS = EconomicParameters()


@dataclass( frozen = True )
class EconomicOutlook:
    """A `Schedule` of `EconomicParameters` over the horizon. The Forecast asks for the
    segment in effect on an interval's start date; where none covers, rates are flat zero."""

    schedule : Schedule[ EconomicParameters ] = Schedule()

    @classmethod
    def constant( cls, parameters : EconomicParameters ) -> 'EconomicOutlook':
        """One set of rates for the whole horizon (a single unbounded segment)."""
        return cls( Schedule.constant( parameters ) )

    def parameters_at( self, on_date : date ) -> EconomicParameters:
        """The segment in effect on `on_date`, or flat-zero parameters if none covers it."""
        return self.schedule.at( on_date ) or _FLAT_PARAMETERS

    def asset_rates_at( self, on_date : date ) -> AssetRates:
        """The Period `AssetRates` in effect on `on_date`."""
        return self.parameters_at( on_date ).asset_rates()
