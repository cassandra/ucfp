"""§5 income: the editable income table.

Income is a list of windowed flows -- the income twin of the expense side (see `IncomeFlow`). This
module presents them as one editable table: a row per general income line (salary, consulting, ...)
and a row per rental property's rent, each an `amount` over a `from`/`until` window, plus the
per-subject retire-age shortcut and Social Security. Async-saved like the spending drill, so the
dates the retire age fills show on save.

General income is hand-entered (a WAGES annual stream for now). Rental rent is a monthly item tied to
its property by `property_handle`. Social Security and pension are NOT free-form flows: their amount
is derived from the claiming/start timing (it follows the entitlement), so they stay per-subject
entitlement + timing inputs here.
"""
from dataclasses import replace
from datetime import date

from django import forms

from common.date_window import DateWindow
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.forecast.parameters import WindowedAmount
from ucfp.profile.schemas import GovernmentPensionEntitlement, IncomeFlow
from ucfp.scenario.schemas import RetirementTiming

_RENTAL_INTERVAL = Duration( 1, TimeUnit.MONTH )   # rent is a monthly item; general income a stream


class IncomeTableForm( forms.Form ):
    """The §5 income table: every income flow as an editable row, plus a blank row to add general
    income, the per-subject retire-age shortcut, and Social Security. `apply` rebuilds the profile's
    income flows (rental preserved by `property_handle`, general from the rows), fills any blank
    salary `until` from the retire age, and writes the SS entitlement and the claiming/retirement
    timing."""

    _EXTRA_ROWS = 1

    def __init__( self, data = None, *, profile = None, scenario = None ):
        super().__init__( data )
        self._profile  = profile
        self._scenario = scenario
        self._subjects = list( profile.subjects ) if profile is not None else list()
        flows          = list( profile.income_flows ) if profile is not None else list()
        self._general  = [ flow for flow in flows if flow.property_handle is None ]
        self._rentals  = ( [ asset for asset in profile.assets
                             if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL ]
                           if profile is not None else list() )
        rental_flows   = { flow.property_handle: flow for flow in flows
                           if flow.property_handle is not None }
        self._timing   = { entry.subject_handle: entry
                           for entry in ( scenario.timing if scenario is not None else [] ) }
        self._gov      = { entitlement.subject_handle: entitlement
                           for entitlement in
                           ( profile.government_pension if profile is not None else [] ) }
        self._general_rows = len( self._general ) + self._EXTRA_ROWS
        for i in range( self._general_rows ):
            self._add_general_fields( i, self._general[ i ] if i < len( self._general ) else None )
        for k, rental in enumerate( self._rentals ):
            self._add_rental_fields( k, rental_flows.get( rental.handle ) )
        for m, subject in enumerate( self._subjects ):
            self._add_subject_fields( m, subject )

    # --- field construction ------------------------------------------------

    def _add_general_fields( self, i : int, flow ):
        name    = forms.CharField( required = False, max_length = 100 )
        subject = forms.ChoiceField( required = False, choices = self._subject_choices() )
        if flow is not None:
            name.initial    = flow.name
            subject.initial  = flow.subject_handle
            self.fields[ self._key( 'g', i, 'remove' ) ] = forms.BooleanField( required = False )
        self.fields[ self._key( 'g', i, 'name' ) ]    = name
        self.fields[ self._key( 'g', i, 'subject' ) ] = subject
        self._add_window_fields( 'g', i, flow )

    def _add_rental_fields( self, k : int, flow ):
        self._add_window_fields( 'r', k, flow )

    def _add_window_fields( self, prefix : str, index : int, flow ):
        amount = forms.DecimalField( required = False, min_value = 0 )
        start  = forms.DateField( required = False )
        until  = forms.DateField( required = False )
        if flow is not None and flow.schedule:
            row = flow.schedule[ 0 ]
            amount.initial = row.amount
            start.initial  = row.window.start
            until.initial  = row.window.end
        self.fields[ self._key( prefix, index, 'amount' ) ] = amount
        self.fields[ self._key( prefix, index, 'from' ) ]   = start
        self.fields[ self._key( prefix, index, 'until' ) ]  = until

    def _add_subject_fields( self, m : int, subject ):
        timing = self._timing.get( subject.handle )
        gov    = self._gov.get( subject.handle )
        self.fields[ self._key( 's', m, 'retire' ) ] = forms.IntegerField(
            label = 'retire at age', required = False, min_value = 0, max_value = 120,
            initial = self._age( subject, timing.retirement_date if timing else None ) )
        self.fields[ self._key( 's', m, 'ssamt' ) ] = forms.DecimalField(
            label = 'Social Security (monthly, at full age)', required = False, min_value = 0,
            initial = gov.monthly_at_normal_age if gov is not None else None )
        self.fields[ self._key( 's', m, 'ssage' ) ] = forms.IntegerField(
            label = 'claims at age', required = False, min_value = 0, max_value = 120,
            initial = timing.government_pension_claiming_age if timing is not None else None )

    @staticmethod
    def _key( prefix : str, index : int, part : str ) -> str:
        return f'{prefix}{index}_{part}'

    def _subject_choices( self ) -> list:
        candidates = [ ( subject.handle, subject.name ) for subject in self._subjects ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    @staticmethod
    def _age( subject, on : date ):
        return on.year - subject.birthdate.year if on is not None else None

    # --- template rows -----------------------------------------------------

    @property
    def income_rows( self ) -> list:
        rows = list()
        for i in range( self._general_rows ):
            existing = i < len( self._general )
            rows.append( {
                'kind'    : 'general',
                'name'    : self[ self._key( 'g', i, 'name' ) ],
                'subject' : self[ self._key( 'g', i, 'subject' ) ],
                'amount'  : self[ self._key( 'g', i, 'amount' ) ],
                'from'    : self[ self._key( 'g', i, 'from' ) ],
                'until'   : self[ self._key( 'g', i, 'until' ) ],
                'cadence' : 'year',
                'remove'  : self[ self._key( 'g', i, 'remove' ) ] if existing else None } )
        for k, rental in enumerate( self._rentals ):
            owner = next( ( s.name for s in self._subjects
                            if s.handle == rental.owner_handle ), rental.owner_handle )
            rows.append( {
                'kind'         : 'rental',
                'name'         : rental.name,
                'subject_name' : owner,
                'amount'       : self[ self._key( 'r', k, 'amount' ) ],
                'from'         : self[ self._key( 'r', k, 'from' ) ],
                'until'        : self[ self._key( 'r', k, 'until' ) ],
                'cadence'      : 'month' } )
        return rows

    @property
    def subject_rows( self ) -> list:
        return [ { 'name'   : subject.name,
                   'retire' : self[ self._key( 's', m, 'retire' ) ],
                   'ssamt'  : self[ self._key( 's', m, 'ssamt' ) ],
                   'ssage'  : self[ self._key( 's', m, 'ssage' ) ] }
                 for m, subject in enumerate( self._subjects ) ]

    # --- apply -------------------------------------------------------------

    def apply( self, profile, scenario ):
        retirement = self._retirement_dates()
        flows      = self._general_flows( retirement ) + self._rental_flows()
        updated_profile  = replace(
            profile, income_flows = flows, government_pension = self._entitlements() )
        updated_scenario = replace( scenario, timing = self._merged_timing( retirement ) )
        return updated_profile, updated_scenario

    def _retirement_dates( self ) -> dict:
        """Each subject's retirement date from the retire-age field (the convenience that fills a
        blank salary `until`); None when the age is blank."""
        dates = dict()
        for m, subject in enumerate( self._subjects ):
            age = self.cleaned_data.get( self._key( 's', m, 'retire' ) )
            dates[ subject.handle ] = _at_age( subject.birthdate, age ) if age is not None else None
        return dates

    def _general_flows( self, retirement : dict ) -> list:
        flows = list()
        for i in range( self._general_rows ):
            if i < len( self._general ) and self.cleaned_data.get( self._key( 'g', i, 'remove' ) ):
                continue
            amount  = self.cleaned_data.get( self._key( 'g', i, 'amount' ) )
            subject = self.cleaned_data.get( self._key( 'g', i, 'subject' ) )
            if amount is None or not subject:
                continue
            until = self.cleaned_data.get( self._key( 'g', i, 'until' ) ) or retirement.get( subject )
            window = DateWindow(
                start = self.cleaned_data.get( self._key( 'g', i, 'from' ) ), end = until )
            flows.append( IncomeFlow(
                name = self.cleaned_data.get( self._key( 'g', i, 'name' ) ) or 'Income',
                subject_handle = subject, income_tax_class = IncomeTaxClass.WAGES,
                schedule = [ WindowedAmount( amount, window ) ] ) )
        return flows

    def _rental_flows( self ) -> list:
        flows = list()
        for k, rental in enumerate( self._rentals ):
            amount = self.cleaned_data.get( self._key( 'r', k, 'amount' ) )
            if amount is None:
                continue
            window = DateWindow(
                start = self.cleaned_data.get( self._key( 'r', k, 'from' ) ),
                end = self.cleaned_data.get( self._key( 'r', k, 'until' ) ) )
            flows.append( IncomeFlow(
                name = rental.name, subject_handle = rental.owner_handle,
                income_tax_class = IncomeTaxClass.GROSS_RENTAL,
                schedule = [ WindowedAmount( amount, window ) ],
                interval = _RENTAL_INTERVAL, property_handle = rental.handle ) )
        return flows

    def _entitlements( self ) -> list:
        entitlements = list()
        for m, subject in enumerate( self._subjects ):
            amount = self.cleaned_data.get( self._key( 's', m, 'ssamt' ) )
            if amount is not None:
                entitlements.append( GovernmentPensionEntitlement(
                    subject_handle = subject.handle, monthly_at_normal_age = amount ) )
        return entitlements

    def _merged_timing( self, retirement : dict ) -> list:
        timing = list()
        for m, subject in enumerate( self._subjects ):
            current = self._timing.get( subject.handle ) or RetirementTiming(
                subject_handle = subject.handle )
            timing.append( replace(
                current,
                retirement_date = retirement.get( subject.handle ) or current.retirement_date,
                government_pension_claiming_age = self.cleaned_data.get(
                    self._key( 's', m, 'ssage' ) ) ) )
        return timing


def _at_age( birthdate : date, age : int ) -> date:
    try:
        return birthdate.replace( year = birthdate.year + age )
    except ValueError:   # 29 Feb in a non-leap target year
        return birthdate.replace( year = birthdate.year + age, day = 28 )
