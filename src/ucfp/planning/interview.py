"""The guided interview that builds a plan's initial inputs.

The interview is one *sequential* view over the same Profile (facts) and Scenario (assumptions)
aggregates the free-form edit pages own: a first-time user is walked section by section to populate
them, then edits them directly afterward for surgical changes. This module defines the section
spine -- the ordered steps, each bound to the `Aggregate` it edits and the form that drives it --
and those per-section forms, which map input onto the typed aggregates.

§1 (subjects) and §2 (retirement timing) are built; the rest are declared so the stepper shows the
whole path, and a section becomes live simply by giving it a form.
"""
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum, auto
from typing import Optional

from django import forms

from common.date_window import DateWindow
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass, IncomeTaxClass
from ucfp.forecast.parameters import WindowedAmount
from ucfp.profile.schemas import (
    PARTNER_SUBJECT_HANDLE, PRIMARY_SUBJECT_HANDLE, RENT_OBLIGATION_HANDLE, RESIDENCE_ASSET_HANDLE,
    AssetProfile, CommittedObligation, GovernmentPensionEntitlement, IncomeFlow, LoanProfile,
    Profile, SubjectProfile )
from ucfp.scenario.schemas import LoanPrepayment, RetirementTiming, Scenario
from ucfp.tax.enums import FilingStatus

from .events import EventsForm
from .external_factors import ExternalFactorsForm
from .properties import rentals_context
from .spending import SpendingForm


class Aggregate( Enum ):
    """Which typed aggregate a section reads from and writes to -- the canonical discriminator the
    section spine and the persistence dispatch share, so neither side spells out a bare string."""
    PROFILE  = auto()
    SCENARIO = auto()


@dataclass( frozen = True )
class Section:
    """One step of the interview: a stable `key` (its URL segment), a user-facing `title`, the
    `aggregates` it writes (the Profile, the Scenario, or both), and the `form` that drives it
    (None until the section is built)."""
    key: str
    title: str
    aggregates: tuple = ( Aggregate.PROFILE, )
    form: Optional[ type ] = None
    inner_template: Optional[ str ] = None   # custom content rendered inside the Continue form
    outer_template: Optional[ str ] = None   # custom pane outside the form (manages its own forms)


class SubjectsForm( forms.Form ):
    """§1 -- who the plan is for. Collects one subject, optionally a partner, and *infers* the
    filing status (joint when there is a partner) rather than asking it; the inferred status stays
    editable later in the edit views. `apply_to` writes just this section onto the Profile, leaving
    every other section's facts intact.
    """

    subject_name      = forms.CharField( label = 'Name', max_length = 100 )
    subject_birthdate = forms.DateField( label = 'Birthdate' )
    has_partner       = forms.BooleanField(
        label = 'This plan includes a partner', required = False )
    partner_name      = forms.CharField( label = 'Partner name', max_length = 100, required = False )
    partner_birthdate = forms.DateField( label = 'Partner birthdate', required = False )

    def __init__( self, data = None, *, profile = None, scenario = None ):
        initial = self._initial( profile ) if profile is not None else None
        super().__init__( data, initial = initial )

    @staticmethod
    def _initial( profile : Profile ) -> dict:
        initial = dict()
        if profile.subjects:
            primary = profile.subjects[ 0 ]
            initial[ 'subject_name' ]      = primary.name
            initial[ 'subject_birthdate' ] = primary.birthdate
        if len( profile.subjects ) > 1:
            partner = profile.subjects[ 1 ]
            initial[ 'has_partner' ]       = True
            initial[ 'partner_name' ]      = partner.name
            initial[ 'partner_birthdate' ] = partner.birthdate
        return initial

    def clean( self ):
        cleaned = super().clean()
        if cleaned.get( 'has_partner' ) and not (
                cleaned.get( 'partner_name' ) and cleaned.get( 'partner_birthdate' ) ):
            raise forms.ValidationError(
                "Add the partner's name and birthdate, or clear the partner option." )
        return cleaned

    def apply( self, profile : Profile, scenario : Scenario ):
        updated = replace(
            profile, subjects = self._subjects(), filing_status = self._filing_status() )
        return updated, scenario

    def _subjects( self ) -> list:
        cleaned  = self.cleaned_data
        subjects = [ SubjectProfile(
            handle = PRIMARY_SUBJECT_HANDLE,
            name = cleaned[ 'subject_name' ], birthdate = cleaned[ 'subject_birthdate' ] ) ]
        if cleaned.get( 'has_partner' ):
            subjects.append( SubjectProfile(
                handle = PARTNER_SUBJECT_HANDLE,
                name = cleaned[ 'partner_name' ], birthdate = cleaned[ 'partner_birthdate' ] ) )
        return subjects

    def _filing_status( self ) -> FilingStatus:
        has_partner = self.cleaned_data.get( 'has_partner' )
        return FilingStatus.MARRIED_JOINT if has_partner else FilingStatus.SINGLE


class RetirementForm( forms.Form ):
    """§2 -- when each subject retires. Asks a retirement *age* per subject (the natural unit; the
    date is derived from their birthdate) and writes it onto the scenario's per-subject timing.
    Foundational: these dates drive when wages stop and retirement income starts.

    Fields are built per subject from the Profile (so the count follows §1), and `apply_to` merges
    the date into each subject's existing `RetirementTiming`, leaving the other timing knobs (a
    later section's claiming age, ...) untouched.
    """

    def __init__( self, data = None, *, profile = None, scenario = None ):
        super().__init__( data )
        self._subjects = profile.subjects if profile is not None else []
        self._timing   = self._timing_by_handle( scenario )
        for subject in self._subjects:
            self.fields[ self._age_field( subject.handle ) ] = self._age_field_for( subject )

    @staticmethod
    def _age_field( handle : str ) -> str:
        return f'{handle}_retirement_age'

    @staticmethod
    def _timing_by_handle( scenario : Optional[ Scenario ] ) -> dict:
        timing = scenario.timing if scenario is not None else []
        return { entry.subject_handle: entry for entry in timing }

    def _age_field_for( self, subject : SubjectProfile ) -> forms.IntegerField:
        field    = forms.IntegerField(
            label = f'{subject.name} retires at age', min_value = 0, max_value = 120 )
        existing = self._timing.get( subject.handle )
        if existing is not None and existing.retirement_date is not None:
            field.initial = existing.retirement_date.year - subject.birthdate.year
        return field

    def apply( self, profile : Profile, scenario : Scenario ):
        return profile, replace( scenario, timing = self._merged_timing() )

    def _merged_timing( self ) -> list:
        timing = list()
        for subject in self._subjects:
            age     = self.cleaned_data[ self._age_field( subject.handle ) ]
            current = self._timing.get( subject.handle ) or RetirementTiming(
                subject_handle = subject.handle )
            timing.append(
                replace( current, retirement_date = self._at_age( subject.birthdate, age ) ) )
        return timing

    @staticmethod
    def _at_age( birthdate : date, age : int ) -> date:
        try:
            return birthdate.replace( year = birthdate.year + age )
        except ValueError:  # 29 Feb landing in a non-leap target year
            return birthdate.replace( year = birthdate.year + age, day = 28 )


class HomeForm( forms.Form ):
    """§3 -- the household residence. Owning captures the home's current value and purchase price
    (its cost basis) and, if there is a mortgage, the loan the way a person knows it -- when it
    started, the original amount, the rate, the term -- from which materialization derives the
    balance still owed; an optional current balance overrides that to capture extra principal
    already paid down. Renting captures the monthly rent. The residence is household-owned, so
    there is no "whose home".

    `apply_to` merges only the residence asset, its mortgage, and the rent obligation into the
    Profile by their stable handles, leaving the accounts and other sections' items intact.
    Associated home expenses (property tax, insurance) are seeded later in Spending.
    """

    _OWN  = 'own'
    _RENT = 'rent'
    _TENURE_CHOICES = ( ( _OWN, 'Own' ), ( _RENT, 'Rent' ) )

    _RESIDENCE_HANDLE = RESIDENCE_ASSET_HANDLE
    _MORTGAGE_HANDLE  = 'mortgage'
    _RENT_HANDLE      = RENT_OBLIGATION_HANDLE

    tenure         = forms.ChoiceField( label = 'The residence is', choices = _TENURE_CHOICES )
    home_value     = forms.DecimalField( label = 'Current value', required = False, min_value = 0 )
    purchase_price = forms.DecimalField( label = 'Purchase price', required = False, min_value = 0 )
    has_mortgage   = forms.BooleanField( label = 'There is a mortgage', required = False )
    mortgage_origination = forms.DateField( label = 'Loan start date', required = False )
    mortgage_original_amount = forms.DecimalField(
        label = 'Original loan amount', required = False, min_value = 0 )
    mortgage_rate = forms.DecimalField(
        label = 'Interest rate (%)', required = False, min_value = 0 )
    mortgage_term_years = forms.IntegerField(
        label = 'Loan term (years)', required = False, min_value = 1 )
    mortgage_current_balance = forms.DecimalField(
        label = 'Balance owed now (optional)', required = False, min_value = 0 )
    mortgage_extra_principal = forms.DecimalField(
        label = 'Extra principal per month (optional)', required = False, min_value = 0 )
    monthly_rent = forms.DecimalField( label = 'Monthly rent', required = False, min_value = 0 )

    def __init__( self, data = None, *, profile = None, scenario = None ):
        initial = self._initial( profile, scenario ) if profile is not None else None
        super().__init__( data, initial = initial )

    @classmethod
    def _initial( cls, profile : Profile, scenario : Scenario ) -> dict:
        rent = cls._find( profile.obligations, cls._RENT_HANDLE )
        if rent is not None:
            return { 'tenure': cls._RENT, 'monthly_rent': rent.amount }
        residence = cls._find( profile.assets, cls._RESIDENCE_HANDLE )
        if residence is None:
            return dict()
        initial = {
            'tenure': cls._OWN, 'home_value': residence.opening_value,
            'purchase_price': residence.cost_basis,
        }
        mortgage = cls._find( profile.loans, cls._MORTGAGE_HANDLE )
        initial.update( cls._mortgage_initial( mortgage, scenario ) )
        return initial

    @classmethod
    def _mortgage_initial( cls, mortgage, scenario : Scenario ) -> dict:
        if mortgage is None:
            return dict()
        initial = {
            'has_mortgage'             : True,
            'mortgage_origination'     : mortgage.origination_date,
            'mortgage_original_amount' : mortgage.original_amount,
            'mortgage_rate'            : mortgage.interest_rate.fraction * 100,
            'mortgage_term_years'      : mortgage.original_term.months() // 12,
            'mortgage_current_balance' : mortgage.current_balance,
        }
        prepayment = cls._prepayment_for( scenario )
        if prepayment is not None:
            initial[ 'mortgage_extra_principal' ] = prepayment.annual_amount / 12
        return initial

    @classmethod
    def _prepayment_for( cls, scenario : Scenario ):
        prepayments = scenario.prepayments if scenario is not None else []
        return next(
            ( item for item in prepayments if item.loan_handle == cls._MORTGAGE_HANDLE ), None )

    def clean( self ):
        cleaned = super().clean()
        if cleaned.get( 'tenure' ) == self._OWN:
            self._require( 'home_value', 'Enter the current home value.' )
            if cleaned.get( 'has_mortgage' ):
                self._require( 'mortgage_origination', 'Enter the loan start date.' )
                self._require( 'mortgage_original_amount', 'Enter the original loan amount.' )
                self._require( 'mortgage_rate', 'Enter the interest rate.' )
                self._require( 'mortgage_term_years', 'Enter the loan term.' )
        elif cleaned.get( 'tenure' ) == self._RENT:
            self._require( 'monthly_rent', 'Enter the monthly rent.' )
        return cleaned

    def _require( self, field : str, message : str ):
        if self.cleaned_data.get( field ) is None:
            self.add_error( field, message )

    def apply( self, profile : Profile, scenario : Scenario ):
        updated_profile = replace(
            profile,
            assets      = self._merged( profile.assets, self._RESIDENCE_HANDLE, self._residence() ),
            loans       = self._merged( profile.loans, self._MORTGAGE_HANDLE, self._mortgage() ),
            obligations = self._merged( profile.obligations, self._RENT_HANDLE, self._rent() ) )
        updated_scenario = replace(
            scenario, prepayments = self._merged_prepayments( scenario.prepayments ) )
        return updated_profile, updated_scenario

    def _residence( self ) -> list:
        cleaned = self.cleaned_data
        if cleaned.get( 'tenure' ) != self._OWN:
            return []
        return [ AssetProfile(
            handle = self._RESIDENCE_HANDLE, name = 'Home',
            asset_class = AssetClass.REAL_ESTATE_RESIDENCE,
            opening_value = cleaned[ 'home_value' ], cost_basis = cleaned.get( 'purchase_price' ) ) ]

    def _mortgage( self ) -> list:
        cleaned = self.cleaned_data
        if cleaned.get( 'tenure' ) != self._OWN or not cleaned.get( 'has_mortgage' ):
            return []
        return [ LoanProfile(
            handle = self._MORTGAGE_HANDLE, name = 'Mortgage',
            origination_date = cleaned[ 'mortgage_origination' ],
            original_amount = cleaned[ 'mortgage_original_amount' ],
            interest_rate = Rate.percent( cleaned[ 'mortgage_rate' ] ),
            original_term = Duration( cleaned[ 'mortgage_term_years' ], TimeUnit.YEAR ),
            current_balance = cleaned.get( 'mortgage_current_balance' ),
            interest_class = ExpenseTaxClass.MORTGAGE_INTEREST,
            property_handle = self._RESIDENCE_HANDLE ) ]

    def _rent( self ) -> list:
        cleaned = self.cleaned_data
        if cleaned.get( 'tenure' ) != self._RENT:
            return []
        return [ CommittedObligation(
            handle = self._RENT_HANDLE, name = 'Rent', amount = cleaned[ 'monthly_rent' ],
            cadence = Duration( 1, TimeUnit.MONTH ), expense_tax_class = ExpenseTaxClass.LIVING ) ]

    def _prepayment( self ) -> list:
        cleaned = self.cleaned_data
        extra   = cleaned.get( 'mortgage_extra_principal' )
        if cleaned.get( 'tenure' ) != self._OWN or not cleaned.get( 'has_mortgage' ) or not extra:
            return []
        return [ LoanPrepayment( loan_handle = self._MORTGAGE_HANDLE, annual_amount = extra * 12 ) ]

    def _merged_prepayments( self, existing : list ) -> list:
        kept = [ item for item in existing if item.loan_handle != self._MORTGAGE_HANDLE ]
        return kept + self._prepayment()

    @staticmethod
    def _merged( existing : list, handle : str, replacement : list ) -> list:
        return [ item for item in existing if item.handle != handle ] + replacement

    @staticmethod
    def _find( items : list, handle : str ):
        return next( ( item for item in items if item.handle == handle ), None )


class PropertiesForm:
    """§3 L0 -- the Properties pane. A no-op section form: the residence and the rentals are each
    edited through their own async view, so Continue just advances. It exposes the residence
    sub-form for the pane (the rentals manage themselves)."""

    def __init__( self, data = None, *, profile = None, scenario = None ):
        self._profile  = profile
        self._scenario = scenario

    def is_valid( self ) -> bool:
        return True

    @property
    def residence_form( self ):
        return HomeForm( profile = self._profile, scenario = self._scenario )

    @property
    def rentals( self ) -> list:
        return rentals_context( self._profile )

    def apply( self, profile, scenario ):
        return profile, scenario


class AccountsForm( forms.Form ):
    """§4 -- the household's financial accounts at a high level: a savings (cash) total, an
    investment (taxable) total, and a retirement total per subject. Retirement accounts are
    individual by law, so each is owned by its subject; savings and investments are household.
    Itemizing into individual accounts, other account types, and cost basis is a later drill-down.

    `apply` replaces the financial-account assets in the Profile, leaving the home and any other
    holdings intact, so revisiting re-states just these buckets.
    """

    _SAVINGS_HANDLE    = 'savings'
    _INVESTMENT_HANDLE = 'investment'
    _RETIREMENT_PREFIX = 'retirement-'

    _ACCOUNT_CLASSES = frozenset( (
        AssetClass.CASH, AssetClass.STOCKS, AssetClass.DIVIDEND_STOCKS, AssetClass.BONDS,
        AssetClass.CDS, AssetClass.PRETAX_RETIREMENT, AssetClass.ROTH ) )

    savings    = forms.DecimalField( label = 'Savings (cash)', required = False, min_value = 0 )
    investment = forms.DecimalField( label = 'Investments', required = False, min_value = 0 )

    def __init__( self, data = None, *, profile = None, scenario = None ):
        super().__init__(
            data, initial = self._initial( profile ) if profile is not None else None )
        self._subjects = profile.subjects if profile is not None else []
        for subject in self._subjects:
            self.fields[ self._retirement_field( subject.handle ) ] = forms.DecimalField(
                label = f'{subject.name} retirement savings', required = False, min_value = 0 )

    @staticmethod
    def _retirement_field( handle : str ) -> str:
        return f'retirement_{handle}'

    @classmethod
    def _retirement_handle( cls, handle : str ) -> str:
        return f'{cls._RETIREMENT_PREFIX}{handle}'

    @classmethod
    def _initial( cls, profile : Profile ) -> dict:
        by_handle = { asset.handle: asset for asset in profile.assets }
        initial   = dict()
        if cls._SAVINGS_HANDLE in by_handle:
            initial[ 'savings' ] = by_handle[ cls._SAVINGS_HANDLE ].opening_value
        if cls._INVESTMENT_HANDLE in by_handle:
            initial[ 'investment' ] = by_handle[ cls._INVESTMENT_HANDLE ].opening_value
        for asset in profile.assets:
            if asset.handle.startswith( cls._RETIREMENT_PREFIX ):
                initial[ cls._retirement_field( asset.owner_handle ) ] = asset.opening_value
        return initial

    def apply( self, profile : Profile, scenario : Scenario ):
        kept = [ asset for asset in profile.assets
                 if asset.asset_class not in self._ACCOUNT_CLASSES ]
        return replace( profile, assets = kept + self._accounts() ), scenario

    def _accounts( self ) -> list:
        accounts  = self._bucket( 'savings', self._SAVINGS_HANDLE, 'Savings', AssetClass.CASH )
        accounts += self._bucket(
            'investment', self._INVESTMENT_HANDLE, 'Investments', AssetClass.STOCKS )
        for subject in self._subjects:
            value = self.cleaned_data.get( self._retirement_field( subject.handle ) )
            if value is not None:
                accounts.append( AssetProfile(
                    handle = self._retirement_handle( subject.handle ),
                    name = f'{subject.name} Retirement',
                    asset_class = AssetClass.PRETAX_RETIREMENT,
                    opening_value = value, owner_handle = subject.handle ) )
        return accounts

    def _bucket( self, field : str, handle : str, name : str, asset_class ) -> list:
        value = self.cleaned_data.get( field )
        if value is None:
            return []
        return [ AssetProfile(
            handle = handle, name = name, asset_class = asset_class, opening_value = value ) ]


class IncomeForm( forms.Form ):
    """§5 -- each subject's Social Security and (if still working) salary. Social Security is the
    benefit at full retirement age plus the chosen claiming age; salary is today's wage, which the
    engine stops at retirement (per §2's date). The benefit *amounts* are Profile facts, while the
    claiming age merges into the scenario's per-subject timing, leaving §2's retirement date intact.

    Pension income, hiding salary once a subject has retired, and spousal rules are later
    refinements; here Social Security and salary are offered per subject and left blank if absent.
    """

    _SS_AMOUNT = 'ss_monthly'
    _SS_AGE    = 'ss_claiming_age'
    _SALARY    = 'salary'

    def __init__( self, data = None, *, profile = None, scenario = None ):
        super().__init__(
            data, initial = self._initial( profile, scenario ) if profile is not None else None )
        self._subjects = profile.subjects if profile is not None else []
        self._timing   = self._timing_by_handle( scenario )
        for subject in self._subjects:
            self.fields[ self._field( self._SS_AMOUNT, subject.handle ) ] = forms.DecimalField(
                label = f'{subject.name} Social Security (monthly, at full age)',
                required = False, min_value = 0 )
            self.fields[ self._field( self._SS_AGE, subject.handle ) ] = forms.IntegerField(
                label = f'{subject.name} claims at age',
                required = False, min_value = 0, max_value = 120 )
            self.fields[ self._field( self._SALARY, subject.handle ) ] = forms.DecimalField(
                label = f'{subject.name} salary (annual)', required = False, min_value = 0 )
        self._rentals = ( [ asset for asset in profile.assets
                            if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL ]
                          if profile is not None else [] )
        for rental in self._rentals:
            self.fields[ self._rent_field( rental.handle ) ] = forms.DecimalField(
                label = f'{rental.name} monthly rent', required = False, min_value = 0 )
            self.fields[ self._rent_start_field( rental.handle ) ] = forms.DateField(
                label = f'{rental.name} rent from', required = False )
            self.fields[ self._rent_end_field( rental.handle ) ] = forms.DateField(
                label = f'{rental.name} rent until', required = False )

    @staticmethod
    def _field( prefix : str, handle : str ) -> str:
        return f'{prefix}_{handle}'

    @staticmethod
    def _rent_field( handle : str ) -> str:
        return f'rent_{handle}'

    @staticmethod
    def _rent_start_field( handle : str ) -> str:
        return f'rent_start_{handle}'

    @staticmethod
    def _rent_end_field( handle : str ) -> str:
        return f'rent_end_{handle}'

    @staticmethod
    def _timing_by_handle( scenario : Scenario ) -> dict:
        timing = scenario.timing if scenario is not None else []
        return { entry.subject_handle: entry for entry in timing }

    @classmethod
    def _initial( cls, profile : Profile, scenario : Scenario ) -> dict:
        timing  = cls._timing_by_handle( scenario )
        initial = dict()
        for entitlement in profile.government_pension:
            handle = entitlement.subject_handle
            initial[ cls._field( cls._SS_AMOUNT, handle ) ] = entitlement.monthly_at_normal_age
            entry = timing.get( handle )
            if entry is not None and entry.government_pension_claiming_age is not None:
                initial[ cls._field( cls._SS_AGE, handle ) ] = entry.government_pension_claiming_age
        salary_flows = { flow.subject_handle: flow for flow in profile.income_flows
                         if flow.income_tax_class is IncomeTaxClass.WAGES }
        for handle, flow in salary_flows.items():
            if flow.schedule:
                initial[ cls._field( cls._SALARY, handle ) ] = flow.schedule[ 0 ].amount
        rental_flows = { flow.property_handle: flow for flow in profile.income_flows
                         if flow.property_handle is not None }
        for asset in profile.assets:
            flow = rental_flows.get( asset.handle )
            if flow is not None and flow.schedule:
                row = flow.schedule[ 0 ]
                initial[ cls._rent_field( asset.handle ) ]       = row.amount
                initial[ cls._rent_start_field( asset.handle ) ] = row.window.start
                initial[ cls._rent_end_field( asset.handle ) ]   = row.window.end
        return initial

    def clean( self ):
        cleaned = super().clean()
        for subject in self._subjects:
            amount = cleaned.get( self._field( self._SS_AMOUNT, subject.handle ) )
            age    = cleaned.get( self._field( self._SS_AGE, subject.handle ) )
            if amount is not None and age is None:
                self.add_error(
                    self._field( self._SS_AGE, subject.handle ),
                    'Choose a Social Security claiming age.' )
        return cleaned

    def apply( self, profile : Profile, scenario : Scenario ):
        updated_profile = replace(
            profile, government_pension = self._entitlements(),
            income_flows = self._salary_flows() + self._rental_flows( profile ) )
        updated_scenario = replace( scenario, timing = self._merged_timing() )
        return updated_profile, updated_scenario

    def _salary_flows( self ) -> list:
        """A WAGES income flow per subject with a salary, ending at the subject's retirement (the
        salary-stop date, else §2's retirement date). The retirement age is the convenience that
        fills the `until`; a direct date editor comes later."""
        flows = list()
        for subject in self._subjects:
            amount = self.cleaned_data.get( self._field( self._SALARY, subject.handle ) )
            if amount is None:
                continue
            window = DateWindow( end = self._salary_end( subject.handle ) )
            flows.append( IncomeFlow(
                name = 'Salary', subject_handle = subject.handle,
                income_tax_class = IncomeTaxClass.WAGES,
                schedule = [ WindowedAmount( amount, window ) ] ) )
        return flows

    def _salary_end( self, handle : str ):
        timing = self._timing.get( handle )
        if timing is None:
            return None
        return timing.salary_stop or timing.retirement_date

    def _rental_flows( self, profile : Profile ) -> list:
        """A monthly GROSS_RENTAL income flow per rental with a rent, owned by the property's owner
        and tagged with its `property_handle`. The rent's from/until come from the fields; later
        schedule rows (a sale's truncation) are preserved, and a blank rent keeps any existing flow
        untouched."""
        existing = { flow.property_handle: flow for flow in profile.income_flows
                     if flow.property_handle is not None }
        flows = list()
        for rental in self._rentals:
            amount = self.cleaned_data.get( self._rent_field( rental.handle ) )
            prior  = existing.get( rental.handle )
            if amount is None:
                if prior is not None:
                    flows.append( prior )
                continue
            flows.append( self._rental_flow( rental, amount, prior ) )
        return flows

    def _rental_flow( self, rental, amount, prior ) -> IncomeFlow:
        window = DateWindow(
            start = self.cleaned_data.get( self._rent_start_field( rental.handle ) ),
            end   = self.cleaned_data.get( self._rent_end_field( rental.handle ) ) )
        later  = list( prior.schedule[ 1: ] ) if ( prior is not None and prior.schedule ) else []
        return IncomeFlow(
            name = rental.name, subject_handle = rental.owner_handle,
            income_tax_class = IncomeTaxClass.GROSS_RENTAL,
            schedule = [ WindowedAmount( amount, window ) ] + later,
            interval = Duration( 1, TimeUnit.MONTH ), property_handle = rental.handle )

    def _entitlements( self ) -> list:
        entitlements = list()
        for subject in self._subjects:
            amount = self.cleaned_data.get( self._field( self._SS_AMOUNT, subject.handle ) )
            if amount is not None:
                entitlements.append( GovernmentPensionEntitlement(
                    subject_handle = subject.handle, monthly_at_normal_age = amount ) )
        return entitlements

    def _merged_timing( self ) -> list:
        timing = list()
        for subject in self._subjects:
            current = self._timing.get( subject.handle ) or RetirementTiming(
                subject_handle = subject.handle )
            age = self.cleaned_data.get( self._field( self._SS_AGE, subject.handle ) )
            timing.append( replace( current, government_pension_claiming_age = age ) )
        return timing


# The interview's order, from the input model in issue #4. A section with a form is live; the rest
# are declared so the stepper shows the full path ahead.
SECTIONS = [
    Section( 'subjects'    , 'Who this plan is for', form = SubjectsForm ),
    Section( 'retirement'  , 'Retirement timing', ( Aggregate.SCENARIO, ), RetirementForm ),
    Section( 'properties'  , 'Properties', ( Aggregate.PROFILE, Aggregate.SCENARIO ), PropertiesForm,
             outer_template = 'planning/interview/sections/properties.html' ),
    Section( 'accounts'    , 'Accounts', form = AccountsForm ),
    Section( 'income'      , 'Income', ( Aggregate.PROFILE, Aggregate.SCENARIO ), IncomeForm ),
    Section( 'spending'    , 'Spending', ( Aggregate.SCENARIO, ), SpendingForm,
             outer_template = 'planning/interview/sections/spending.html' ),
    Section( 'events'      , 'Plans & events', ( Aggregate.SCENARIO, ), EventsForm,
             outer_template = 'planning/interview/sections/events.html' ),
    Section( 'external-factors', 'External Factors', ( Aggregate.SCENARIO, ), ExternalFactorsForm,
             inner_template = 'planning/interview/sections/external_factors.html' ),
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
