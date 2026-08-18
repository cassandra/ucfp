"""Enumerations for the accounts (double-entry core) app."""
from common.labeled_enum import LabeledEnum


class SideType( LabeledEnum ):
    """A side of the double-entry ledger.

    The single Debit/Credit vocabulary, used for two distinct roles: an
    account's normal balance side (Account.account_normal_type) and the side an
    entry posts to (Entry.entry_direction).
    """

    DEBIT  = ( 'Debit'  , 'The left side of the ledger.' )
    CREDIT = ( 'Credit' , 'The right side of the ledger.' )


class AccountType( LabeledEnum ):
    """A top-level classification of accounts in double-entry bookkeeping.

    Each type has a normal balance side (see normal_side): the side on which an
    increase to the account is recorded, and on which a positive natural balance
    sits.
    """

    ASSET     = ( 'Asset'     , 'Resources owned (cash, investments, property).' )
    LIABILITY = ( 'Liability' , 'Obligations owed to others (loans, debts).' )
    EQUITY    = ( 'Equity'    , 'Residual interest: assets minus liabilities.' )
    REVENUE   = ( 'Income'    , 'Inflows that increase equity (income).' )
    EXPENSE   = ( 'Expense'   , 'Outflows that decrease equity (costs).' )

    @property
    def normal_side( self ) -> SideType:
        return _ACCOUNT_TYPE_NORMAL_SIDE[ self ]


# The normal balance side per account type: Assets and Expenses are debit-normal;
# Liabilities, Equity, and Revenue are credit-normal. This drives only the
# display sign of natural_balance and validation -- never the core arithmetic,
# which is uniformly credit-positive.
_ACCOUNT_TYPE_NORMAL_SIDE = {
    AccountType.ASSET     : SideType.DEBIT,
    AccountType.LIABILITY : SideType.CREDIT,
    AccountType.EQUITY    : SideType.CREDIT,
    AccountType.REVENUE   : SideType.CREDIT,
    AccountType.EXPENSE   : SideType.DEBIT,
}


class CurrencyType( LabeledEnum ):
    """ISO 4217 currencies supported for accounts and transactions."""

    USD = ( 'US Dollar'         , 'United States dollar.' )
    EUR = ( 'Euro'              , 'European Union euro.' )
    GBP = ( 'British Pound'     , 'Pound sterling.' )
    JPY = ( 'Japanese Yen'      , 'Japanese yen.' )
    CAD = ( 'Canadian Dollar'   , 'Canadian dollar.' )
    AUD = ( 'Australian Dollar' , 'Australian dollar.' )
    CHF = ( 'Swiss Franc'       , 'Swiss franc.' )

    @classmethod
    def default( cls ):
        return cls.USD

    @property
    def symbol( self ) -> str:
        """The currency symbol that prefixes a formatted amount (e.g. '$')."""
        return _CURRENCY_FORMAT[ self ][ 0 ]

    @property
    def minor_unit_digits( self ) -> int:
        """The currency's fractional digits (2 for dollars/euros, 0 for yen)."""
        return _CURRENCY_FORMAT[ self ][ 1 ]

    def format( self, amount, with_minor_units : bool = False ) -> str:
        """`amount` as a display string: the symbol, thousands separators, and -- by default --
        whole units (the magnitude planning works in). Pass `with_minor_units` for the currency's
        fractional digits. A negative amount carries a leading minus before the symbol; a value that
        rounds to zero at the display precision carries none (no stray '-$0' from a sub-unit negative)."""
        digits  = self.minor_unit_digits if with_minor_units else 0
        rounded = round( amount, digits )        # round to display precision, then take the sign from the
        sign    = '-' if rounded < 0 else ''     # result -- a rounds-to-zero value is not negative
        return f'{sign}{self.symbol}{abs( rounded ):,.{digits}f}'


# Display formatting per currency: (symbol that prefixes the amount, fractional digits). The single
# source behind CurrencyType.symbol / .minor_unit_digits / .format.
_CURRENCY_FORMAT = {
    CurrencyType.USD : ( '$'    , 2 ),
    CurrencyType.EUR : ( '€'    , 2 ),
    CurrencyType.GBP : ( '£'    , 2 ),
    CurrencyType.JPY : ( '¥'    , 0 ),
    CurrencyType.CAD : ( 'CA$'  , 2 ),
    CurrencyType.AUD : ( 'A$'   , 2 ),
    CurrencyType.CHF : ( 'CHF ' , 2 ),
}


class SystemAccountRole( LabeledEnum ):
    """Well-known, app-managed accounts beyond the per-type roots.

    The per-type root accounts are identified structurally (parentless, with an
    account_type), so they need no role. This enum names the other system
    accounts that build_standard_chart creates and that are protected from deletion
    and closing.
    """

    OPENING_BALANCES = ( 'Opening Balances' , 'Equity counterpart for a Journal opening seed.' )
    UNREALIZED_GAINS = ( 'Unrealized Gains' , 'Equity counterpart for unrealized appreciation.' )
    EXTERNAL_RECEIPTS = (
        'External Receipts', 'Equity counterpart for non-taxable value received from outside.' )
    EXTERNAL_DISBURSEMENTS = (
        'External Disbursements', 'Equity counterpart for non-deductible value given away.' )
    TAXES_PAYABLE = (
        'Taxes Payable', 'Liability for tax assessed this year and paid the following year.' )
    ESTIMATED_FUTURE_TAXES = (
        'Estimated Future Taxes',
        'Liability for the estimated tax embedded in pre-tax balances and unrealized gains.' )
    DEFERRED_TAX_RESERVE = (
        'Deferred Tax Reserve',
        'Equity counterpart for the Estimated Future Taxes provision.' )


class AssetClass( LabeledEnum ):
    """A behavior-equivalence class for asset accounts in projection.

    Each class groups asset accounts the projection treats identically -- the same
    growth, distribution, basis, and realization behavior. It is the dispatch key
    for that behavior; the behavior itself lives in the projection layer, not here.
    "Tax-free", "ordinary", etc. are *tax-treatment* classes a class maps into, a
    separate taxonomy -- so Roth is its own behavior class, not a generic
    tax-free bucket. Set on asset accounts only (see Account.asset_class).
    """

    CASH                    = ( 'Cash & Savings'            , 'Cash and savings; the income/expense hub.' )
    STOCKS                  = ( 'Stocks'                    , 'Growth equities; appreciation only.' )
    DIVIDEND_STOCKS         = ( 'Dividend Stocks'           , 'Dividend equities, plus appreciation.' )
    BONDS                   = ( 'Bonds'                     , 'Bonds paying interest, with appreciation.' )
    CDS                     = ( 'CDs'                       , 'Certificates of deposit paying interest.' )
    REAL_ESTATE_RESIDENCE   = ( 'Real Estate (Residence)'   , 'A primary residence held for appreciation.' )
    REAL_ESTATE_RENTAL      = ( 'Real Estate (Rental)'      , 'Rental property: income and depreciation.' )
    REAL_ESTATE_SECOND_HOME = ( 'Real Estate (Second Home)' , 'A personal-use second home: appreciates, no depreciation or residence exclusion.' )
    PRETAX_RETIREMENT       = ( 'Pre-Tax Retirement'        , 'IRA/401(k); withdrawals are ordinary income.' )
    ROTH                    = ( 'Roth Retirement'           , 'Qualified withdrawals tax-free; no RMDs.' )
    PRECIOUS_METALS         = ( 'Precious Metals'           , 'Gold, silver; taxed as collectibles.' )
    COLLECTIBLES            = ( 'Collectibles'              , 'Art, jewelry and similar collectibles.' )
    DEPRECIATING            = ( 'Depreciating Assets'       , 'Vehicles; depreciate over time.' )

    @property
    def accrues_unrealized_gains( self ) -> bool:
        """Whether this class accumulates unrealized gain/loss in a valuation
        companion account, rather than being held at face value."""
        return self not in _NON_APPRECIATING_ASSET_CLASSES

    @property
    def seeds_at_zero_basis( self ) -> bool:
        """Whether holdings of this class carry zero tax basis -- a domain rule, not a planner
        choice: a pre-tax retirement account's contributions were untaxed (the whole
        withdrawal is ordinary), and a Roth is modeled at zero basis so a withdrawal realizes
        wholly into the tax-free class. Such a holding's `cost_basis` must be 0 (its whole
        value seeds as unrealized gain); other classes carry a real basis."""
        return self in _ZERO_BASIS_ASSET_CLASSES

    @property
    def is_retirement_account( self ) -> bool:
        """Whether this class is a contribution-limited retirement account (pre-tax or Roth) -- the
        concept several call sites actually need: an owner whose age drives the early-withdrawal
        penalty and RMDs, a holding a sweep may not target, a holding a contribution must. Distinct
        from `seeds_at_zero_basis` (a tax-basis fact); the two coincide only because both retirement
        classes seed at zero basis today, a coincidence that ends once Roth carries a real basis."""
        return self in _RETIREMENT_ASSET_CLASSES

    @property
    def distribution_income_class( self ):
        """The income tax-class a yield distribution (dividend/interest) credits,
        or None for classes that distribute no yield. Rental income is amount-based
        (not a yield) and is supplied separately, so rental is not included here."""
        return _DISTRIBUTION_INCOME_CLASS.get( self )

    @property
    def realized_gain_income_class( self ):
        """The income tax-class the gain realized on a sale or withdrawal is
        recognized in, or None for classes that recognize no realized gain:
        face-value classes (cash, CDs) that carry no gain, and personal-use
        depreciating assets, whose value change stays a permanent *unrealized*
        item (already in net worth) rather than being realized as income -- so a
        car trade-in is a plain asset->cash swap, not a tax-free income spike."""
        return _REALIZED_GAIN_INCOME_CLASS.get( self )

    @property
    def is_real_estate( self ) -> bool:
        """Whether this class is real property -- a residence, a second home, or a rental. The single
        source of truth for the several "is this real estate?" call sites (it is not a money account, so
        it is excluded from transfers; it is the thing a property sale sells; it appreciates at the
        real-estate rate), so adding a real-estate class cannot silently miss one. Rental-specific
        behavior (depreciation, rental income) keys on `REAL_ESTATE_RENTAL` directly, not on this."""
        return self in _REAL_ESTATE_ASSET_CLASSES

    @property
    def supports_partial_draw( self ) -> bool:
        """Whether the cash-funding waterfall may cover a shortfall by selling a slice of a holding of
        this class -- true for the liquid financial classes (a fraction of a brokerage or retirement
        balance sells readily). Real estate and possessions are indivisible: they sell whole through a
        dedicated sale handler, not shaved to the exact shortfall, so they are excluded here and the
        waterfall routes them to that handler instead of a partial `realize`."""
        return self in _PARTIALLY_DRAWABLE_ASSET_CLASSES


# Cash-like classes carried at face value: their return is distributed as interest
# income, not accrued as appreciation, so they have no valuation companion.
_NON_APPRECIATING_ASSET_CLASSES = frozenset( ( AssetClass.CASH, AssetClass.CDS ) )


# Retirement classes that carry zero tax basis (a domain rule): the whole holding value is
# realized on withdrawal/conversion -- pre-tax as ordinary, Roth as tax-free. Their
# cost_basis must be 0 (validated on the input), so the whole value seeds as unrealized gain.
_ZERO_BASIS_ASSET_CLASSES = frozenset(
    ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH ) )


# The contribution-limited retirement classes (pre-tax + Roth) -- the "is this a retirement account?"
# concept, kept distinct from `_ZERO_BASIS_ASSET_CLASSES` (a tax-basis fact) even though the two sets
# coincide today, so decoupling Roth's basis cannot silently change the retirement-account checks.
_RETIREMENT_ASSET_CLASSES = frozenset(
    ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH ) )


# The real-property classes (see `is_real_estate`) -- a residence, a second home, or a rental. Grouped
# once here so the "is this real estate?" call sites cannot drift apart as classes are added.
_REAL_ESTATE_ASSET_CLASSES = frozenset(
    ( AssetClass.REAL_ESTATE_RESIDENCE, AssetClass.REAL_ESTATE_SECOND_HOME,
      AssetClass.REAL_ESTATE_RENTAL ) )


# The liquid financial classes a cash shortfall can draw a slice of (see `supports_partial_draw`).
# Everything outside this set -- real estate, possessions -- is indivisible and sold whole through a
# sale handler instead. Cash itself is the funded hub, never a draw source, so it is excluded.
_PARTIALLY_DRAWABLE_ASSET_CLASSES = frozenset(
    ( AssetClass.CDS, AssetClass.BONDS, AssetClass.STOCKS, AssetClass.DIVIDEND_STOCKS,
      AssetClass.ROTH, AssetClass.PRETAX_RETIREMENT ) )


class RealPropertyType( LabeledEnum ):
    """The depreciation class of rental real estate -- a general real-estate
    distinction (the US recovery periods that depend on it live in the tax engine).
    Irrelevant for a personal residence, which is not depreciated."""

    RESIDENTIAL = ( 'Residential', 'Residential rental real estate.' )
    COMMERCIAL  = ( 'Commercial' , 'Nonresidential (commercial) real estate.' )


class IncomeTaxClass( LabeledEnum ):
    """A tax-treatment class for revenue (income) accounts.

    Groups income a tax engine treats identically -- the same rate, netting, and
    inclusion rules. It is the chart's identity for income; how each class is rated
    and netted lives inside a TaxEngine's parameters, not here. Set on revenue
    accounts only (see Account.income_tax_class). US-oriented; another
    jurisdiction's engine maps these to its own rules.
    """

    WAGES               = ( 'Wages', 'Earned income; ordinary rate, plus FICA.' )
    ORDINARY            = ( 'Ordinary Income', 'Ordinary rate, not investment income (e.g. a taxable receipt).' )
    PENSION             = (
        'Pension',
        'A pension/annuity benefit; taxed as ordinary income, but tracked apart from generic ordinary '
        'income because it is retirement income a state may exempt.' )
    RETIREMENT_DISTRIBUTION = (
        'Retirement Distribution', 'Pre-tax retirement withdrawals and RMDs; taxed as ordinary income.' )
    TAXABLE_INTEREST    = ( 'Taxable Interest', 'Ordinary rate; net investment income (bank/bond/CD).' )
    QUALIFIED_DIVIDENDS = ( 'Qualified Dividends', 'Preferential rate; not netted with losses.' )
    LONG_TERM_GAINS     = ( 'Long-Term Gains', 'Preferential rate; netted with losses.' )
    SHORT_TERM_GAINS    = ( 'Short-Term Gains', 'Ordinary rate; netted separately.' )
    RESIDENCE_SECTION_121_GAIN = (
        'Residence Gain', 'Primary-residence gain; §121 exclusion, remainder long-term.' )
    SECOND_HOME_GAIN    = ( 'Second Home Gain', 'Personal-use second-home gain; long-term, no exclusion, loss non-deductible.' )
    RENTAL_SALE_GAIN    = ( 'Rental Sale Gain', 'Gain on a rental sale; long-term, with accumulated depreciation recaptured as §1250.' )
    SECTION_1250_GAIN   = ( 'Section 1250 Gain', 'Unrecaptured depreciation; 25% max rate.' )
    COLLECTIBLES_GAINS  = ( 'Collectibles Gains', 'Collectibles; 28% max rate.' )
    SOCIAL_SECURITY     = ( 'Social Security', 'Benefits; partial-inclusion rule.' )
    GROSS_RENTAL        = ( 'Gross Rental', 'Gross rents; netted with expenses in-period.' )
    TAX_FREE            = ( 'Tax-Free', 'Excluded from tax everywhere (Roth).' )
    TAX_EXEMPT_INTEREST = ( 'Tax-Exempt Interest', 'Untaxed, but counts in SS/ACA MAGI (muni).' )

    @property
    def is_owner_attributed( self ) -> bool:
        """Whether an asset's income of this class is tracked per owning subject -- a revenue account
        in the owner's name -- rather than at the household level. A pre-tax retirement distribution
        lands in the account owner's name (it is that person's RMD/withdrawal); a taxable gain stays
        household (joint on a joint return)."""
        return self in _OWNER_ATTRIBUTED_INCOME_CLASSES


# Income tax-classes whose asset income is attributed to the owning subject (a per-person revenue
# account), not the household -- a retirement distribution carries the owner's name; capital gains do
# not (they are joint on a joint return).
_OWNER_ATTRIBUTED_INCOME_CLASSES = frozenset( { IncomeTaxClass.RETIREMENT_DISTRIBUTION } )


# The income tax-class each distributing asset class credits with its yield
# (dividends/interest). Classes absent here distribute no yield; rental income is
# amount-based and supplied separately, so rental is not listed.
_DISTRIBUTION_INCOME_CLASS = {
    AssetClass.CASH            : IncomeTaxClass.TAXABLE_INTEREST,
    AssetClass.BONDS           : IncomeTaxClass.TAXABLE_INTEREST,
    AssetClass.CDS             : IncomeTaxClass.TAXABLE_INTEREST,
    AssetClass.DIVIDEND_STOCKS : IncomeTaxClass.QUALIFIED_DIVIDENDS,
}


# The income tax-class the gain realized on a sale or withdrawal is recognized in,
# per asset class. Absent classes recognize no realized gain. Cash and CDs are face
# value (no gain to realize). DEPRECIATING is absent deliberately: a personal-use
# vehicle's decline is already carried gradually as unrealized depreciation (in net
# worth), and it is never a tax event, so realizing it on trade-in would only post a
# tax-free loss to the income statement -- confusing noise. Its trade-in instead just
# clears the holding to cash (see `Bookkeeper.realize`), leaving the loss unrealized.
_REALIZED_GAIN_INCOME_CLASS = {
    AssetClass.STOCKS                  : IncomeTaxClass.LONG_TERM_GAINS,
    AssetClass.DIVIDEND_STOCKS         : IncomeTaxClass.LONG_TERM_GAINS,
    AssetClass.BONDS                   : IncomeTaxClass.LONG_TERM_GAINS,
    AssetClass.REAL_ESTATE_RESIDENCE   : IncomeTaxClass.RESIDENCE_SECTION_121_GAIN,
    AssetClass.REAL_ESTATE_RENTAL      : IncomeTaxClass.RENTAL_SALE_GAIN,
    AssetClass.REAL_ESTATE_SECOND_HOME : IncomeTaxClass.SECOND_HOME_GAIN,
    AssetClass.PRETAX_RETIREMENT       : IncomeTaxClass.RETIREMENT_DISTRIBUTION,
    AssetClass.ROTH                    : IncomeTaxClass.TAX_FREE,
    AssetClass.PRECIOUS_METALS         : IncomeTaxClass.COLLECTIBLES_GAINS,
    AssetClass.COLLECTIBLES            : IncomeTaxClass.COLLECTIBLES_GAINS,
}


class ExpenseTaxClass( LabeledEnum ):
    """A tax-treatment class for expense accounts -- the expense mirror of
    IncomeTaxClass.

    Spans deductibility classes (how a lifestyle expense affects the tax
    computation) and tax-payment classes (the tax outputs themselves). It is the
    chart's identity for expenses; how each is treated lives in a TaxEngine's
    parameters. Set on expense accounts only (see Account.expense_tax_class).
    """

    LIVING                  = ( 'Living', 'Non-deductible living expenses (the bulk).' )
    MEDICAL                 = ( 'Medical', 'Deductible above the AGI floor.' )
    MORTGAGE_INTEREST       = ( 'Mortgage Interest', 'Itemizable mortgage interest, with limits.' )
    SALT                    = ( 'SALT', 'Property tax booked here; the engine folds in the modeled state income tax; capped.' )
    CHARITABLE              = ( 'Charitable', 'Itemizable charitable gifts; AGI-limited.' )
    NON_DEDUCTIBLE_INTEREST = ( 'Non-Deductible Interest', 'Auto/personal/credit-card interest.' )
    RENTAL_EXPENSE          = ( 'Rental Expense', 'Netted against rental income.' )
    ORDINARY_INCOME_TAX     = ( 'Ordinary Income Tax', 'Tax on ordinary income at the bracket rates.' )
    CAPITAL_GAINS_TAX       = (
        'Capital Gains Tax', 'Preferential-rate tax on long-term gains and qualified dividends.' )
    SECTION_1250_TAX        = (
        'Section 1250 Tax', 'Tax on unrecaptured §1250 depreciation, capped at its own rate.' )
    COLLECTIBLES_TAX        = ( 'Collectibles Tax', 'Tax on collectibles gains, capped at its own rate.' )
    EMPLOYMENT_TAX          = (
        'FICA (Social Security & Medicare)',
        'Social Security + Medicare on wages (employee FICA); withheld in-year, not income tax.' )
    NIIT                    = ( 'Net Investment Income Tax', '3.8% net investment income tax.' )
    STATE_INCOME_TAX        = (
        'State Income Tax', 'A flat per-state rate on federal AGI; a simplified estimate, not real brackets.' )
    EARLY_WITHDRAWAL_PENALTY = (
        'Early-Withdrawal Penalty', '10% additional tax on early retirement withdrawals.' )

    @property
    def is_tax_payment( self ) -> bool:
        """Whether this is a tax-payment class -- one a TaxEngine settles its charges into
        (a tax the household pays) -- as opposed to a deductibility class it reads from
        spending. The projection creates a chart account for each so settlement can post."""
        return self in _TAX_PAYMENT_EXPENSE_CLASSES


# The expense classes a TaxEngine settles charges/credits into (see
# ExpenseTaxClass.is_tax_payment); kept beside the enum as its single source of truth.
_TAX_PAYMENT_EXPENSE_CLASSES = frozenset( (
    ExpenseTaxClass.ORDINARY_INCOME_TAX,
    ExpenseTaxClass.CAPITAL_GAINS_TAX,
    ExpenseTaxClass.SECTION_1250_TAX,
    ExpenseTaxClass.COLLECTIBLES_TAX,
    ExpenseTaxClass.EMPLOYMENT_TAX,
    ExpenseTaxClass.NIIT,
    ExpenseTaxClass.STATE_INCOME_TAX,
    ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY,
) )


# The union of the three per-type "class" taxonomies -- the class axis of an account, named
# where code handles a class generically (asset, income, or expense) rather than one kind.
# Liability and Equity have no class taxonomy.
AccountClass = AssetClass | IncomeTaxClass | ExpenseTaxClass
