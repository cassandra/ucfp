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
    REVENUE   = ( 'Revenue'   , 'Inflows that increase equity (income).' )
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
        fractional digits. A negative amount carries a leading minus before the symbol."""
        digits = self.minor_unit_digits if with_minor_units else 0
        sign   = '-' if amount < 0 else ''
        return f'{sign}{self.symbol}{abs( amount ):,.{digits}f}'


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
    DEPRECIATING            = ( 'Depreciating Assets'       , 'Vehicles, boats; depreciate over time.' )

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
    def distribution_income_class( self ):
        """The income tax-class a yield distribution (dividend/interest) credits,
        or None for classes that distribute no yield. Rental income is amount-based
        (not a yield) and is supplied separately, so rental is not included here."""
        return _DISTRIBUTION_INCOME_CLASS.get( self )

    @property
    def realized_gain_income_class( self ):
        """The income tax-class the gain realized on a sale or withdrawal is
        recognized in. None for face-value classes (cash, CDs) that never carry a
        gain to realize; TAX_FREE for personal-use depreciating assets, whose
        gain/loss is recognized in the books but excluded from tax."""
        return _REALIZED_GAIN_INCOME_CLASS.get( self )


# Cash-like classes carried at face value: their return is distributed as interest
# income, not accrued as appreciation, so they have no valuation companion.
_NON_APPRECIATING_ASSET_CLASSES = frozenset( ( AssetClass.CASH, AssetClass.CDS ) )


# Retirement classes that carry zero tax basis (a domain rule): the whole holding value is
# realized on withdrawal/conversion -- pre-tax as ordinary, Roth as tax-free. Their
# cost_basis must be 0 (validated on the input), so the whole value seeds as unrealized gain.
_ZERO_BASIS_ASSET_CLASSES = frozenset(
    ( AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH ) )


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
    ORDINARY            = ( 'Ordinary Income', 'Ordinary rate, not investment income (pension, IRA).' )
    TAXABLE_INTEREST    = ( 'Taxable Interest', 'Ordinary rate; net investment income (bank/bond/CD).' )
    QUALIFIED_DIVIDENDS = ( 'Qualified Dividends', 'Preferential rate; not netted with losses.' )
    LONG_TERM_GAINS     = ( 'Long-Term Gains', 'Preferential rate; netted with losses.' )
    SHORT_TERM_GAINS    = ( 'Short-Term Gains', 'Ordinary rate; netted separately.' )
    RESIDENCE_SECTION_121_GAIN = (
        'Residence Gain', 'Primary-residence gain; §121 exclusion, remainder long-term.' )
    SECOND_HOME_GAIN    = ( 'Second Home Gain', 'Personal-use second-home gain; long-term, no exclusion, loss non-deductible.' )
    SECTION_1250_GAIN   = ( 'Section 1250 Gain', 'Unrecaptured depreciation; 25% max rate.' )
    COLLECTIBLES_GAINS  = ( 'Collectibles Gains', 'Collectibles; 28% max rate.' )
    SOCIAL_SECURITY     = ( 'Social Security', 'Benefits; partial-inclusion rule.' )
    GROSS_RENTAL        = ( 'Gross Rental', 'Gross rents; netted with expenses in-period.' )
    TAX_FREE            = ( 'Tax-Free', 'Excluded from tax everywhere (Roth).' )
    TAX_EXEMPT_INTEREST = ( 'Tax-Exempt Interest', 'Untaxed, but counts in SS/ACA MAGI (muni).' )


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
# per asset class. Cash and CDs are absent (face value -- no gain to realize).
# Depreciating personal assets map to TAX_FREE: their gain/loss is real to the books
# but not taxable (a personal-use loss is non-deductible, gains are rare), so it is
# recognized and then excluded from tax -- a deliberate simplification.
_REALIZED_GAIN_INCOME_CLASS = {
    AssetClass.STOCKS                  : IncomeTaxClass.LONG_TERM_GAINS,
    AssetClass.DIVIDEND_STOCKS         : IncomeTaxClass.LONG_TERM_GAINS,
    AssetClass.BONDS                   : IncomeTaxClass.LONG_TERM_GAINS,
    AssetClass.REAL_ESTATE_RESIDENCE   : IncomeTaxClass.RESIDENCE_SECTION_121_GAIN,
    AssetClass.REAL_ESTATE_RENTAL      : IncomeTaxClass.LONG_TERM_GAINS,
    AssetClass.REAL_ESTATE_SECOND_HOME : IncomeTaxClass.SECOND_HOME_GAIN,
    AssetClass.PRETAX_RETIREMENT       : IncomeTaxClass.ORDINARY,
    AssetClass.ROTH                    : IncomeTaxClass.TAX_FREE,
    AssetClass.PRECIOUS_METALS         : IncomeTaxClass.COLLECTIBLES_GAINS,
    AssetClass.COLLECTIBLES            : IncomeTaxClass.COLLECTIBLES_GAINS,
    AssetClass.DEPRECIATING            : IncomeTaxClass.TAX_FREE,
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
    SALT                    = ( 'SALT', 'State/local income + property tax; capped.' )
    CHARITABLE              = ( 'Charitable', 'Itemizable charitable gifts; AGI-limited.' )
    NON_DEDUCTIBLE_INTEREST = ( 'Non-Deductible Interest', 'Auto/personal/credit-card interest.' )
    RENTAL_EXPENSE          = ( 'Rental Expense', 'Netted against rental income.' )
    INCOME_TAX              = ( 'Income Tax', 'Income tax paid (incl. AMT).' )
    PAYROLL_TAX             = ( 'Payroll Tax', 'FICA / Medicare on wages.' )
    NIIT                    = ( 'Net Investment Income Tax', '3.8% net investment income tax.' )
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
    ExpenseTaxClass.INCOME_TAX,
    ExpenseTaxClass.PAYROLL_TAX,
    ExpenseTaxClass.NIIT,
    ExpenseTaxClass.EARLY_WITHDRAWAL_PENALTY,
) )


# The union of the three per-type "class" taxonomies -- the class axis of an account, named
# where code handles a class generically (asset, income, or expense) rather than one kind.
# Liability and Equity have no class taxonomy.
AccountClass = AssetClass | IncomeTaxClass | ExpenseTaxClass
