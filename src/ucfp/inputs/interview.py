"""The guided interview that builds a plan's initial inputs.

The interview is one *sequential* view over the same Profile (facts), Plans (the contemplated
future), and Assumptions (the exogenous outlook) aggregates the free-form edit pages own: a
first-time user is walked section by section to populate them, then edits them directly afterward
for surgical changes. This module defines the section spine -- the ordered steps, each bound to the
`Aggregate` it edits and the form that drives it -- and those per-section forms, which map input
onto the typed aggregates.

§1 (subjects) and §2 (retirement timing) are built; the rest are declared so the stepper shows the
whole path, and a section becomes live simply by giving it a form.
"""
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Optional

from django import forms

from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import (
    PARTNER_SUBJECT_HANDLE, PRIMARY_SUBJECT_HANDLE, RENT_OBLIGATION_HANDLE, RESIDENCE_ASSET_HANDLE,
    RESIDENCE_MORTGAGE_HANDLE, AssetProfile, CommittedObligation, Debt, Profile, SubjectProfile )
from ucfp.inputs.plans.schemas import Plans
from ucfp.jurisdiction.enums import FilingStatus, JurisdictionConcept, JurisdictionType
from ucfp.jurisdiction.labels import local_label

from .credit_card import CreditCardPlanForm
from .debt_plan import DebtPlanForm
from .debts import DebtsForm
from .events import EventsForm
from .external_factors import ExternalFactorsSectionForm
from .income import IncomeTableForm
from .properties import PANES, PossessionsForm, properties_context
from .spending import SpendingForm
from .widgets import IsoDateInput


class Aggregate( Enum ):
    """Which typed aggregate a section reads from and writes to -- the canonical discriminator the
    section spine and the persistence dispatch share, so neither side spells out a bare string."""
    PROFILE     = auto()
    PLANS       = auto()
    ASSUMPTIONS = auto()


@dataclass( frozen = True )
class Section:
    """One step of the interview: a stable `key` (its URL segment), a user-facing `title`, the
    `aggregates` it writes, and the `form` that drives it (None until the section is built)."""
    key: str
    title: str
    aggregates: tuple = ( Aggregate.PROFILE, )
    form: Optional[ type ] = None
    inner_template: Optional[ str ] = None   # custom content rendered inside the Continue form
    outer_template: Optional[ str ] = None   # custom pane outside the form (manages its own forms)


class SubjectsForm( forms.Form ):
    """§1 -- who the plan is for. Collects one subject and optionally a partner, and *infers* the
    filing status (joint when there is a partner) rather than asking it -- the engine supports only
    single vs joint, both fixed by whether a partner exists, so there is nothing to choose. The tax
    basis (jurisdiction and that inferred filing status) is shown read-only beside the inputs.
    `apply` writes just this section onto the Profile, leaving every other section's facts intact.

    Non-blocking, like every self-saving section: nothing is required, an incomplete person is simply
    not held (its subject is built only once both name and birthdate are present), and the filing
    status is left unset until a primary person exists -- the forecast readiness check is the gate
    that a person and filing status are present.
    """

    subject_name      = forms.CharField( label = 'Name', max_length = 100, required = False )
    subject_birthdate = forms.DateField(
        label = 'Birthdate', required = False,
        widget = IsoDateInput( context = AppConst.DATE_CONTEXT_BIRTHDATE ) )
    partner_name      = forms.CharField( label = 'Name', max_length = 100, required = False )
    partner_birthdate = forms.DateField(
        label = 'Birthdate', required = False,
        widget = IsoDateInput( context = AppConst.DATE_CONTEXT_BIRTHDATE ) )

    def __init__( self, data = None, *, profile = None, plans = None ):
        initial = self._initial( profile ) if profile is not None else None
        super().__init__( data, initial = initial )
        self._profile = profile

    # --- Tax-basis pane (read-only) ----------------------------------------

    @property
    def jurisdiction_label( self ) -> str:
        """The household's tax jurisdiction, shown read-only (US federal is the only one today)."""
        jurisdiction = self._profile.jurisdiction_type if self._profile else JurisdictionType.US_FEDERAL
        return jurisdiction.label

    @property
    def filing_status_label( self ) -> str:
        """The filing status the engine will use, read from the saved profile and shown read-only. It
        reflects saved facts, so it updates on save rather than as the partner is edited -- there is
        nothing to choose while single vs joint is fixed by whether a partner exists. A dash until a
        primary person is entered (the filing status is unset until then)."""
        status = self._profile.filing_status if self._profile is not None else None
        return status.label if status is not None else '—'

    @staticmethod
    def _initial( profile : Profile ) -> dict:
        initial = dict()
        if profile.subjects:
            primary = profile.subjects[ 0 ]
            initial[ 'subject_name' ]      = primary.name
            initial[ 'subject_birthdate' ] = primary.birthdate
        if len( profile.subjects ) > 1:
            partner = profile.subjects[ 1 ]
            initial[ 'partner_name' ]      = partner.name
            initial[ 'partner_birthdate' ] = partner.birthdate
        return initial

    def clean( self ):
        cleaned = super().clean()
        # A partner is present exactly when both of their fields are filled; one alone is an
        # incomplete entry, not a signal to drop the partner silently.
        if bool( cleaned.get( 'partner_name' ) ) != bool( cleaned.get( 'partner_birthdate' ) ):
            raise forms.ValidationError(
                "Enter both the partner's name and birthdate, or leave both blank." )
        return cleaned

    def apply( self, profile : Profile, plans : Plans ):
        subjects = self._subjects()
        updated  = replace(
            profile, subjects = subjects, filing_status = self._filing_status( subjects ) )
        return updated, plans

    def _has_partner( self ) -> bool:
        """A partner is inferred from filled fields -- no separate opt-in checkbox. `clean` has
        already rejected the half-filled case, so both fields are set together or not at all."""
        return bool( self.cleaned_data.get( 'partner_name' )
                     and self.cleaned_data.get( 'partner_birthdate' ) )

    def _has_primary( self ) -> bool:
        """A primary person is inferred from both of their fields being filled -- non-blocking, so a
        half-entered person simply is not held (and no partner is held without a primary)."""
        return bool( self.cleaned_data.get( 'subject_name' )
                     and self.cleaned_data.get( 'subject_birthdate' ) )

    def _subjects( self ) -> list:
        cleaned  = self.cleaned_data
        if not self._has_primary():
            return list()
        subjects = [ SubjectProfile(
            handle = PRIMARY_SUBJECT_HANDLE,
            name = cleaned[ 'subject_name' ], birthdate = cleaned[ 'subject_birthdate' ] ) ]
        if self._has_partner():
            subjects.append( SubjectProfile(
                handle = PARTNER_SUBJECT_HANDLE,
                name = cleaned[ 'partner_name' ], birthdate = cleaned[ 'partner_birthdate' ] ) )
        return subjects

    @classmethod
    def _filing_status( cls, subjects : list ) -> Optional[ FilingStatus ]:
        """The filing status the built household implies -- unset with no primary person, else single
        vs joint by whether a partner is present."""
        if not subjects:
            return None
        return cls._filing_status_for( len( subjects ) > 1 )

    @staticmethod
    def _filing_status_for( has_partner : bool ) -> FilingStatus:
        """Single vs joint from partner presence."""
        return FilingStatus.MARRIED_JOINT if has_partner else FilingStatus.SINGLE


class SubjectsSectionForm:
    """§1 section wrapper. The Subjects pane self-saves through `SubjectsView`, so this section form
    only carries the flow: it always validates and its `apply` is a no-op, leaving Next to advance
    without re-saving. It exposes the editor (`subjects_form`) for the pane -- built once so the pane
    and the read-only tax-basis readout beside it share one instance."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self.subjects_form = SubjectsForm( profile = profile )

    def is_valid( self ) -> bool:
        return True

    def apply( self, profile, plans ):
        return profile, plans


class HomeForm( forms.Form ):
    """§3 -- the household residence. Owning captures the home's current value, purchase price (its
    cost basis), and any mortgage balance still owed; renting captures the monthly rent. The
    residence is household-owned, so there is no "whose home". The mortgage balance is a convenience
    surface on the home for the one `Debt` secured against the residence -- the same debt the Debts
    section shows (read-only there, since it is owned here).

    `apply` merges only the residence asset, its mortgage debt, and the rent obligation into the
    Profile by their stable handles, leaving the accounts and other sections' items intact.
    Associated home expenses (property tax, insurance) are seeded later in Spending.
    """

    _OWN  = 'own'
    _RENT = 'rent'
    _TENURE_CHOICES = ( ( _OWN, 'Own' ), ( _RENT, 'Rent' ) )

    _RESIDENCE_HANDLE = RESIDENCE_ASSET_HANDLE
    _MORTGAGE_HANDLE  = RESIDENCE_MORTGAGE_HANDLE
    _RENT_HANDLE      = RENT_OBLIGATION_HANDLE

    tenure           = forms.ChoiceField(
        label = 'Do you own or rent your home?', choices = _TENURE_CHOICES, initial = _OWN,
        widget = forms.RadioSelect( attrs = { 'class' : AppConst.SWITCH_CONTROL_CLASS } ) )
    home_value       = forms.DecimalField( label = 'Current value', required = False, min_value = 0 )
    purchase_price   = forms.DecimalField( label = 'Purchase price', required = False, min_value = 0 )
    mortgage_balance = forms.DecimalField(
        label = 'Mortgage balance owed (optional)', required = False, min_value = 0 )
    monthly_rent     = forms.DecimalField( label = 'Monthly rent', required = False, min_value = 0 )

    def __init__( self, data = None, *, profile = None, plans = None ):
        initial = self._initial( profile ) if profile is not None else None
        super().__init__( data, initial = initial )

    @classmethod
    def _initial( cls, profile : Profile ) -> dict:
        rent = cls._find( profile.obligations, cls._RENT_HANDLE )
        if rent is not None:
            return { 'tenure': cls._RENT, 'monthly_rent': rent.amount }
        residence = cls._find( profile.assets, cls._RESIDENCE_HANDLE )
        if residence is None:
            return dict()
        initial   = {
            'tenure': cls._OWN, 'home_value': residence.opening_value,
            'purchase_price': residence.cost_basis,
        }
        mortgage = cls._find( profile.debts, cls._MORTGAGE_HANDLE )
        if mortgage is not None:
            initial[ 'mortgage_balance' ] = mortgage.balance
        return initial

    def apply( self, profile : Profile, plans : Plans ):
        existing_mortgage = self._find( profile.debts, self._MORTGAGE_HANDLE )
        updated_profile = replace(
            profile,
            assets      = self._merged( profile.assets, self._RESIDENCE_HANDLE, self._residence() ),
            debts       = self._merged(
                profile.debts, self._MORTGAGE_HANDLE, self._mortgage( existing_mortgage ) ),
            obligations = self._merged( profile.obligations, self._RENT_HANDLE, self._rent() ) )
        return updated_profile, plans

    def _residence( self ) -> list:
        # Non-blocking: an owned home materializes only once its value is entered; until then it
        # simply is not written (no hard error mid-entry), the forecast run being the real gate.
        cleaned = self.cleaned_data
        if cleaned.get( 'tenure' ) != self._OWN or cleaned.get( 'home_value' ) is None:
            return []
        return [ AssetProfile(
            handle = self._RESIDENCE_HANDLE, name = 'Home',
            asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
            opening_value = cleaned[ 'home_value' ], cost_basis = cleaned.get( 'purchase_price' ) ) ]

    def _mortgage( self, existing ) -> list:
        # The residence-secured mortgage debt, present only for an owned home with a balance entered.
        # The home is a balance-only convenience surface onto the one debt; the name and kind the
        # Debts section may have set are preserved rather than overwritten here.
        cleaned = self.cleaned_data
        if cleaned.get( 'tenure' ) != self._OWN or cleaned.get( 'mortgage_balance' ) is None:
            return []
        return [ Debt(
            handle = self._MORTGAGE_HANDLE,
            name = existing.name if existing is not None else 'Mortgage',
            kind = existing.kind if existing is not None else DebtKind.MORTGAGE,
            balance = cleaned[ 'mortgage_balance' ], secured_asset = self._RESIDENCE_HANDLE ) ]

    def _rent( self ) -> list:
        cleaned = self.cleaned_data
        if cleaned.get( 'tenure' ) != self._RENT or cleaned.get( 'monthly_rent' ) is None:
            return []
        return [ CommittedObligation(
            handle = self._RENT_HANDLE, name = 'Rent', amount = cleaned[ 'monthly_rent' ],
            cadence = Duration( 1, TimeUnit.MONTH ), expense_tax_class = ExpenseTaxClass.LIVING ) ]

    @staticmethod
    def _merged( existing : list, handle : str, replacement : list ) -> list:
        return [ item for item in existing if item.handle != handle ] + replacement

    @staticmethod
    def _find( items : list, handle : str ):
        return next( ( item for item in items if item.handle == handle ), None )


class PropertiesForm:
    """§3 L0 -- the Properties pane. A no-op section form: the residence, the rentals, and the second
    homes are each edited through their own async view, so Continue just advances. It exposes the
    residence sub-form and the property lists for the pane (the rentals and second homes manage
    themselves)."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile  = profile
        self._plans = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def residence_form( self ):
        return HomeForm( profile = self._profile, plans = self._plans )

    @property
    def property_panes( self ) -> list:
        """Each mortgaged-property pane's render context for the Property section -- its heading, its
        holdings, and the template config (ids, URL names, wording) from the shared `PropertyPane`.
        The section loops over these, so a new property kind is one pane, not another hand-wired
        block."""
        return [ { 'heading': pane.heading,
                   'properties': properties_context( self._profile, pane.asset_class ),
                   **pane.template_context() }
                 for pane in PANES ]

    @property
    def possessions_form( self ):
        return PossessionsForm( profile = self._profile, plans = self._plans )

    def apply( self, profile, plans ):
        return profile, plans


class AccountsForm( forms.Form ):
    """§4 -- the household's financial accounts, one optional total per engine asset class the
    projection distinguishes. Nothing is required: a user enters a single total or itemizes across
    classes, as detailed as they care to be. The household's taxable holdings are shared; retirement
    is individual by law, so each subject has their own pre-tax and tax-free (Roth) totals.

    Splitting a class into named individual accounts, and cost basis, are later drill-downs. `apply`
    replaces the financial-account assets in the Profile, leaving the home and other holdings intact.
    """

    # The household's taxable holdings: (field name, stable handle, engine asset class).
    _TAXABLE = (
        ( 'cash', 'cash', AssetClass.CASH ),
        ( 'stocks', 'stocks', AssetClass.STOCKS ),
        ( 'dividend_stocks', 'dividend-stocks', AssetClass.DIVIDEND_STOCKS ),
        ( 'bonds', 'bonds', AssetClass.BONDS ),
        ( 'cds', 'cds', AssetClass.CDS ),
    )
    # Each subject's tax-advantaged retirement, per wrapper the projection distinguishes:
    # (field prefix, handle prefix, engine asset class, jurisdiction concept for the local label).
    _RETIREMENT = (
        ( 'pretax', 'pretax-', AssetClass.PRETAX_RETIREMENT, JurisdictionConcept.PRETAX_RETIREMENT ),
        ( 'roth', 'roth-', AssetClass.ROTH, JurisdictionConcept.TAX_FREE_RETIREMENT ),
    )
    _ACCOUNT_CLASSES = frozenset(
        [ item[ 2 ] for item in _TAXABLE ] + [ item[ 2 ] for item in _RETIREMENT ] )

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__(
            data, initial = self._initial( profile ) if profile is not None else None )
        self._subjects = profile.subjects if profile is not None else []
        jurisdiction   = ( profile.jurisdiction_type if profile is not None
                           else JurisdictionType.US_FEDERAL )
        for name, _handle, asset_class in self._TAXABLE:
            self.fields[ name ] = forms.DecimalField(
                label = asset_class.label, required = False, min_value = 0 )
        for subject in self._subjects:
            for prefix, _handle_prefix, _asset_class, concept in self._RETIREMENT:
                self.fields[ self._retire_field( prefix, subject.handle ) ] = forms.DecimalField(
                    label = local_label( jurisdiction, concept ), required = False, min_value = 0 )

    @staticmethod
    def _retire_field( prefix : str, handle : str ) -> str:
        return f'{prefix}_{handle}'

    @property
    def taxable_fields( self ) -> list:
        """The household taxable-account fields, in class order (for the template)."""
        return [ self[ name ] for name, _handle, _cls in self._TAXABLE ]

    @property
    def retirement_groups( self ) -> list:
        """The retirement fields grouped one block per subject (for the template)."""
        return [ { 'subject' : subject.name,
                   'fields'  : [ self[ self._retire_field( prefix, subject.handle ) ]
                                 for prefix, _hp, _cls, _c in self._RETIREMENT ] }
                 for subject in self._subjects ]

    @classmethod
    def _initial( cls, profile : Profile ) -> dict:
        by_handle = { asset.handle : asset for asset in profile.assets }
        initial   = dict()
        for name, handle, _asset_class in cls._TAXABLE:
            if handle in by_handle:
                initial[ name ] = by_handle[ handle ].opening_value
        for subject in profile.subjects:
            for prefix, handle_prefix, _asset_class, _concept in cls._RETIREMENT:
                handle = f'{handle_prefix}{subject.handle}'
                if handle in by_handle:
                    initial[ cls._retire_field( prefix, subject.handle ) ] = \
                        by_handle[ handle ].opening_value
        return initial

    def apply( self, profile : Profile, plans : Plans ):
        kept = [ asset for asset in profile.assets
                 if asset.asset_class not in self._ACCOUNT_CLASSES ]
        return replace( profile, assets = kept + self._accounts() ), plans

    def _accounts( self ) -> list:
        accounts = []
        for name, handle, asset_class in self._TAXABLE:
            value = self.cleaned_data.get( name )
            if value is not None:
                accounts.append( AssetProfile(
                    handle = handle, name = asset_class.label,
                    asset_class = asset_class, opening_value = value ) )
        for subject in self._subjects:
            for prefix, handle_prefix, asset_class, _concept in self._RETIREMENT:
                value = self.cleaned_data.get( self._retire_field( prefix, subject.handle ) )
                if value is not None:
                    accounts.append( AssetProfile(
                        handle = f'{handle_prefix}{subject.handle}',
                        name = f'{subject.name} {asset_class.label}',
                        asset_class = asset_class, opening_value = value,
                        owner_handle = subject.handle ) )
        return accounts


class AccountsSectionForm:
    """§4 section wrapper. The Accounts pane self-saves through `AccountsView`, so this section form
    only carries the flow: it always validates and its `apply` is a no-op, leaving Next to advance
    without re-saving. It exposes the editor (`accounts_form`) for the pane -- the same shape the other
    self-saving sections use."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile = profile
        self._plans   = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def accounts_form( self ) -> AccountsForm:
        return AccountsForm( profile = self._profile, plans = self._plans )

    def apply( self, profile, plans ):
        return profile, plans


class IncomeSectionForm:
    """§5 L0 -- the income pane. A no-op section form: income is edited and saved through the
    `IncomeTableView`, so Continue just advances. It exposes the income table for the pane."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile  = profile
        self._plans = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def income_table( self ):
        return IncomeTableForm( profile = self._profile, plans = self._plans )

    def apply( self, profile, plans ):
        return profile, plans


class DebtsSectionForm:
    """§ Debts L0 -- the Debts pane. A no-op section form: the debts are edited and saved through
    `DebtsView`, so Continue just advances. It exposes the one debts list -- every debt, mortgages
    included, in the order the user thinks of them."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile = profile
        self._plans   = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def debts_form( self ):
        return DebtsForm( profile = self._profile, plans = self._plans )

    def apply( self, profile, plans ):
        return profile, plans


class DebtPlanSectionForm:
    """§ Debt plan L0 -- the pane. A no-op section form: the amortizing loans' repayment terms and
    the credit cards' paydown strategies are each edited and saved through their own async view
    (`DebtPlanView`, `CreditCardView`), so Continue just advances. It exposes both forms, which read
    the declared debts."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        self._profile = profile
        self._plans   = plans

    def is_valid( self ) -> bool:
        return True

    @property
    def debt_plan_form( self ):
        return DebtPlanForm( profile = self._profile, plans = self._plans )

    @property
    def credit_card_form( self ):
        return CreditCardPlanForm( profile = self._profile, plans = self._plans )

    def apply( self, profile, plans ):
        return profile, plans


# The interview's order, from the input model in issue #4. A section with a form is live; the rest
# are declared so the stepper shows the full path ahead.
SECTIONS = [
    Section( 'subjects'    , 'Who this plan is for', form = SubjectsSectionForm,
             outer_template = 'inputs/interview/sections/subjects.html' ),
    Section( 'accounts'    , 'Accounts', form = AccountsSectionForm,
             outer_template = 'inputs/interview/sections/accounts.html' ),
    Section( 'income'      , 'Income', ( Aggregate.PROFILE, Aggregate.PLANS ), IncomeSectionForm,
             outer_template = 'inputs/interview/sections/income.html' ),
    Section( 'properties'  , 'Property', ( Aggregate.PROFILE, Aggregate.PLANS ), PropertiesForm,
             outer_template = 'inputs/interview/sections/properties.html' ),
    # The one liabilities view: every debt as a flat list of loans (mortgages included), each also
    # adjustable on its property. Facts only; the repayment plan per debt is the Debt plan step below,
    # which opens the Plans flow.
    Section( 'debt'        , 'Debts', form = DebtsSectionForm,
             outer_template = 'inputs/interview/sections/debts.html' ),
    # The Plans side of the debts: how each amortizing debt is repaid (rate, term, extra principal).
    # Opens the Plans flow, reading the debts declared just above.
    Section( 'debt-plan'   , 'Debt plan', ( Aggregate.PLANS, ), DebtPlanSectionForm,
             outer_template = 'inputs/interview/sections/debt_plan.html' ),
    Section( 'spending'    , 'Spending', ( Aggregate.PLANS, ), SpendingForm,
             outer_template = 'inputs/interview/sections/spending.html' ),
    Section( 'events'      , 'Plans & events', ( Aggregate.PLANS, ), EventsForm,
             outer_template = 'inputs/interview/sections/events.html' ),
    Section( 'external-factors', 'External Factors', ( Aggregate.ASSUMPTIONS, ),
             ExternalFactorsSectionForm,
             outer_template = 'inputs/interview/sections/external_factors.html' ),
]


def section_for( key : str ) -> Optional[ Section ]:
    return next( ( section for section in SECTIONS if section.key == key ), None )


def applicable_sections( profile : Profile ) -> list:
    """The sections that apply given what's been entered so far -- the conditionality hook, and the
    real payoff of a linear flow. Every section applies for now; later this prunes or adds sections
    from prior answers (a partner expands the people detail, owning a home adds the home section)."""
    return list( SECTIONS )


def next_section_after( sections : list, key : str ) -> Optional[ Section ]:
    """The next live (form-backed) section after `key` within `sections`, or None when the
    interview is complete -- where Continue goes."""
    keys      = [ section.key for section in sections ]
    following = sections[ keys.index( key ) + 1 : ] if key in keys else []
    return next( ( section for section in following if section.form is not None ), None )


# ===== Flows =====
# The interview is three flows the user can run separately or, guided, in sequence. A section's flow
# is its primary aggregate, so the spine partitions with no extra metadata: Profile (facts) first,
# then Plans, then Assumptions. The straddle sections (properties, income) write Profile and Plans
# and live in the Profile flow, co-presenting their plan fields for entry convenience.

FLOWS = [
    ( 'profile'    , 'Profile' ),
    ( 'plans'      , 'Plans' ),
    ( 'assumptions', 'Assumptions' ),
]


def flow_of( section : Section ) -> str:
    if Aggregate.PROFILE in section.aggregates:
        return 'profile'
    if Aggregate.PLANS in section.aggregates:
        return 'plans'
    return 'assumptions'


def flow_title( flow_key : str ) -> str:
    return next( title for key, title in FLOWS if key == flow_key )


def sections_in_flow( flow_key : str ) -> list:
    return [ section for section in SECTIONS if flow_of( section ) == flow_key ]


def first_section_of_flow( flow_key : str ) -> Optional[ Section ]:
    """The first live (form-backed) section of a flow, or None if it has none yet."""
    return next( ( section for section in sections_in_flow( flow_key )
                   if section.form is not None ), None )


def next_flow_entry( flow_key : str ) -> Optional[ Section ]:
    """The first live section of the flow after `flow_key` in guided order, or None at the end --
    where the guided interview advances when a flow completes."""
    keys = [ key for key, _ in FLOWS ]
    for key in keys[ keys.index( flow_key ) + 1 : ]:
        section = first_section_of_flow( key )
        if section is not None:
            return section
    return None
