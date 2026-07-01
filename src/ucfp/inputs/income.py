"""§5 income: the editable income table.

Income is a list of windowed flows -- the income twin of the expense side (see `IncomeFlow`). This
module presents them as one editable table: a row per general income line (salary, consulting, ...),
a row per rental property's rent, and two entitlement rows per subject (Social Security, pension).
Each row carries an `amount` over a `from`/`until` window. The **date is canonical**; the `age`
column beside it is a convenience that a small client-side helper (`inputs.js`) keeps in sync
with the date both ways. The server therefore just reads the date, with one fallback for a JS-less
client: a window endpoint with no date but a filled age is resolved from the subject's birthdate
(`_endpoint`).

The table auto-saves -- every edit persists in the background -- so validation is deliberately
non-blocking: an incomplete row simply does not materialize (no flow / no entitlement written),
rather than raising a hard error that would fight the user mid-entry. Genuine input errors (a
malformed date, a negative amount) still surface, on the re-render the server sends when a save is
invalid. The real gate on incompleteness is the forecast run (materialization raises on, e.g., a
benefit with no claiming date). (A client-side "this row won't take effect yet" hint is a deferred
nicety -- it must live in the client to stay correct under silent, no-re-render saves.)

General income is hand-entered (a WAGES annual stream for now). Rental rent is a monthly item tied to
its property by `property_handle`. Social Security and pension are NOT free-form flows: their realized
amount is the engine's job, derived from the stated benefit plus the claiming/start date -- so their
rows capture only that benefit (FRA / base) and that date, and feed the profile entitlement facts and
the Plans timing rather than an `IncomeFlow`.
"""
import json
from dataclasses import replace
from datetime import date

from django import forms

from common.date_window import DateWindow
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass, IncomeTaxClass
from ucfp.environment.constants import AppConst
from ucfp.forecast.parameters import WindowedAmount
from ucfp.inputs.profile.schemas import GovernmentPensionEntitlement, IncomeFlow, PensionEntitlement
from ucfp.inputs.plans.schemas import RetirementTiming
from ucfp.inputs.widgets import IsoDateInput

_RENTAL_INTERVAL = Duration( 1, TimeUnit.MONTH )   # rent is a monthly item; general income a stream


class IncomeTableForm( forms.Form ):
    """The §5 income table: every income flow as an editable row, a blank row to add general income,
    and two entitlement rows per subject (Social Security, pension). `apply` rebuilds the profile's
    income flows (rental preserved by `property_handle`, general from the rows), writes the SS and
    pension entitlement facts from the entitlement rows, and writes the claiming/start dates into the
    Plans timing. Resolution is date-canonical with an age fallback (`_endpoint`)."""

    _EXTRA_ROWS = 1

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._profile  = profile
        self._plans = plans
        self._subjects = list( profile.subjects ) if profile is not None else list()
        flows          = list( profile.income_flows ) if profile is not None else list()
        self._general  = [ flow for flow in flows if flow.property_handle is None ]
        self._rentals  = ( [ asset for asset in profile.assets
                             if asset.asset_class is AssetClass.REAL_ESTATE_RENTAL ]
                           if profile is not None else list() )
        rental_flows   = { flow.property_handle: flow for flow in flows
                           if flow.property_handle is not None }
        self._timing   = { entry.subject_handle: entry
                           for entry in ( plans.timing if plans is not None else [] ) }
        self._gov      = { entitlement.subject_handle: entitlement
                           for entitlement in
                           ( profile.government_pension if profile is not None else [] ) }
        self._pension  = { pension.subject_handle: pension
                           for pension in ( profile.pensions if profile is not None else [] ) }
        self._general_rows = len( self._general ) + self._EXTRA_ROWS
        for i in range( self._general_rows ):
            self._add_general_fields( i, self._general[ i ] if i < len( self._general ) else None )
        for k, rental in enumerate( self._rentals ):
            self._add_rental_fields( k, rental_flows.get( rental.handle ) )
        for m, subject in enumerate( self._subjects ):
            self._add_entitlement_fields( m, subject )

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
        row       = flow.schedule[ 0 ] if flow is not None and flow.schedule else None
        birthdate = self._birthdate( flow.subject_handle ) if flow is not None else None
        self._add_window_fields( 'g', i, row, birthdate )

    def _add_rental_fields( self, k : int, flow ):
        row = flow.schedule[ 0 ] if flow is not None and flow.schedule else None
        self._add_window_fields( 'r', k, row, None, with_age = False )

    def _add_entitlement_fields( self, m : int, subject ):
        """Social Security and pension as table rows for the subject: a stated benefit (FRA / base)
        plus an election date with an age helper. The realized amount is the engine's job; this only
        captures the benefit and when it is claimed/started."""
        timing    = self._timing.get( subject.handle )
        gov       = self._gov.get( subject.handle )
        pension   = self._pension.get( subject.handle )
        claiming  = timing.government_pension_claiming_date if timing is not None else None
        start     = timing.pension_start if timing is not None else None
        ss_amount  = gov.monthly_at_normal_age if gov is not None else None
        pen_amount = pension.base_annual_amount if pension is not None else None
        self._add_entitlement_row( m, 'ss', ss_amount, claiming, subject.birthdate )
        self._add_entitlement_row( m, 'pen', pen_amount, start, subject.birthdate )

    def _add_entitlement_row( self, m : int, kind : str, amount_initial, date_initial, birthdate ):
        self.fields[ self._key( 's', m, f'{kind}amt' ) ] = forms.DecimalField(
            required = False, min_value = 0, initial = amount_initial )
        self.fields[ self._key( 's', m, f'{kind}_from' ) ] = forms.DateField(
            required = False, initial = date_initial, widget = IsoDateInput() )
        self.fields[ self._key( 's', m, f'{kind}_from_age' ) ] = forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = self._derived_age( date_initial, birthdate ) )
        self._link_age( self._key( 's', m, f'{kind}_from' ), self._key( 's', m, f'{kind}_from_age' ),
                        birthdate = birthdate )

    def _add_window_fields( self, prefix : str, index : int, row, birthdate, with_age = True ):
        """The amount + from/until date fields for a row, seeded from a `WindowedAmount` `row`. When
        `with_age`, an age field beside each date is seeded with the date's whole-year age (the client
        keeps the two in sync; the server falls back to the age only when its date is blank)."""
        start_on = row.window.start if row is not None else None
        end_on   = row.window.end if row is not None else None
        self.fields[ self._key( prefix, index, 'amount' ) ] = forms.DecimalField(
            required = False, min_value = 0, initial = row.amount if row is not None else None )
        self.fields[ self._key( prefix, index, 'from' ) ]  = forms.DateField(
            required = False, initial = start_on, widget = IsoDateInput() )
        self.fields[ self._key( prefix, index, 'until' ) ] = forms.DateField(
            required = False, initial = end_on, widget = IsoDateInput() )
        if with_age:
            self.fields[ self._key( prefix, index, 'from_age' ) ] = forms.IntegerField(
                required = False, min_value = 0, max_value = 120,
                initial = self._derived_age( start_on, birthdate ) )
            self.fields[ self._key( prefix, index, 'until_age' ) ] = forms.IntegerField(
                required = False, min_value = 0, max_value = 120,
                initial = self._derived_age( end_on, birthdate ) )
            # A general row's birthdate follows its chosen subject, so the client resolves it live
            # from the subject field rather than a baked-in date.
            subject_field = self._key( prefix, index, 'subject' )
            self._link_age( self._key( prefix, index, 'from' ),
                            self._key( prefix, index, 'from_age' ), subject_field = subject_field )
            self._link_age( self._key( prefix, index, 'until' ),
                            self._key( prefix, index, 'until_age' ), subject_field = subject_field )

    def _link_age( self, date_key : str, age_key : str, *, subject_field = None, birthdate = None ):
        """Tag a date/age pair so `inputs.js` can keep them in sync: each carries a class and a
        pointer to its partner's element id, plus how to find the subject's birthdate -- either a
        live `subject_field` (general rows) or a fixed `birthdate` (entitlement rows). The shared
        hooks come from `AppConst` so the client and this markup cannot drift."""
        shared = {}
        if subject_field is not None:
            shared[ f'data-{AppConst.SUBJECT_FIELD_DATA_ATTR}' ] = f'id_{subject_field}'
        if birthdate is not None:
            shared[ f'data-{AppConst.BIRTHDATE_DATA_ATTR}' ] = birthdate.isoformat()
        self.fields[ date_key ].widget.attrs.update(
            { 'class' : AppConst.DATE_FIELD_CLASS,
              f'data-{AppConst.AGE_FIELD_DATA_ATTR}' : f'id_{age_key}', **shared } )
        self.fields[ age_key ].widget.attrs.update(
            { 'class' : AppConst.AGE_FIELD_CLASS,
              f'data-{AppConst.DATE_FIELD_DATA_ATTR}' : f'id_{date_key}', **shared } )

    def _birthdate( self, handle : str ):
        subject = next( ( s for s in self._subjects if s.handle == handle ), None )
        return subject.birthdate if subject is not None else None

    @staticmethod
    def _derived_age( on : date, birthdate : date ):
        """The whole-year age a date falls on -- the inverse of `_at_age` (which lands on the
        birthday), so round-tripping an age through a date and back is stable."""
        if on is None or birthdate is None:
            return None
        return on.year - birthdate.year

    @staticmethod
    def _key( prefix : str, index : int, part : str ) -> str:
        return f'{prefix}{index}_{part}'

    def _subject_choices( self ) -> list:
        candidates = [ ( subject.handle, subject.name ) for subject in self._subjects ]
        if len( candidates ) == 1:
            return candidates
        return [ ( '', 'Choose...' ) ] + candidates

    def _default_subject( self, subject : str ) -> str:
        """The chosen subject, or the sole subject when there is only one (so a single-subject plan
        need not pick); None when several and none was chosen."""
        if subject:
            return subject
        return self._subjects[ 0 ].handle if len( self._subjects ) == 1 else None

    # --- date-canonical resolution -----------------------------------------

    def _endpoint( self, prefix : str, index : int, part : str, birthdate ):
        """A window endpoint date. The date field is canonical (the client keeps it filled from the
        age helper); the age is consulted only as a fallback for a JS-less client that submitted an
        age but no date."""
        on = self.cleaned_data.get( self._key( prefix, index, part ) )
        if on is not None:
            return on
        age = self.cleaned_data.get( self._key( prefix, index, f'{part}_age' ) )
        if age is not None and birthdate is not None:
            return _at_age( birthdate, age )
        return None

    # --- template rows -----------------------------------------------------

    @property
    def income_rows( self ) -> list:
        rows = list()
        for i in range( self._general_rows ):
            existing = i < len( self._general )
            subject  = self[ self._key( 'g', i, 'subject' ) ]
            rows.append( {
                'kind'     : 'general',
                'name'     : self[ self._key( 'g', i, 'name' ) ],
                'subject'  : subject,
                'amount'   : self[ self._key( 'g', i, 'amount' ) ],
                'from'     : self[ self._key( 'g', i, 'from' ) ],
                'from_age' : self[ self._key( 'g', i, 'from_age' ) ],
                'until'    : self[ self._key( 'g', i, 'until' ) ],
                'until_age': self[ self._key( 'g', i, 'until_age' ) ],
                'cadence'  : 'year',
                'remove'   : self[ self._key( 'g', i, 'remove' ) ] if existing else None } )
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
        for m, subject in enumerate( self._subjects ):
            rows.append( self._entitlement_row(
                m, subject, 'ss', 'Social Security', 'month', 'benefit at full retirement age' ) )
            rows.append( self._entitlement_row(
                m, subject, 'pen', 'Pension', 'year', 'base benefit' ) )
        return rows

    def _entitlement_row( self, m, subject, kind, name, cadence, note ) -> dict:
        """An entitlement row: a stated benefit and a claiming/start date with an age helper. No
        `until` (it runs for life) and no `remove` (the entitlement row is always offered); a blank
        amount simply means the subject has no such benefit."""
        return {
            'kind'         : 'entitlement',
            'subject_name' : subject.name,
            'birthdate'    : subject.birthdate,
            'name'         : name,
            'amount'       : self[ self._key( 's', m, f'{kind}amt' ) ],
            'from'         : self[ self._key( 's', m, f'{kind}_from' ) ],
            'from_age'     : self[ self._key( 's', m, f'{kind}_from_age' ) ],
            'cadence'      : cadence,
            'note'         : note }

    @property
    def subject_birthdates_json( self ) -> str:
        """Subject handle -> ISO birthdate, for the client age<->date helper to resolve a general
        row's birthdate from its currently chosen subject."""
        return json.dumps( { subject.handle: subject.birthdate.isoformat()
                             for subject in self._subjects } )

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        flows = self._general_flows() + self._rental_flows()
        updated_profile  = replace(
            profile, income_flows = flows,
            government_pension = self._entitlements(), pensions = self._pensions() )
        updated_plans = replace( plans, timing = self._merged_timing() )
        return updated_profile, updated_plans

    def _general_flows( self ) -> list:
        flows = list()
        for i in range( self._general_rows ):
            if i < len( self._general ) and self.cleaned_data.get( self._key( 'g', i, 'remove' ) ):
                continue
            amount  = self.cleaned_data.get( self._key( 'g', i, 'amount' ) )
            subject = self._default_subject( self.cleaned_data.get( self._key( 'g', i, 'subject' ) ) )
            if amount is None or not subject:
                continue
            birthdate = self._birthdate( subject )
            window    = DateWindow(
                start = self._endpoint( 'g', i, 'from', birthdate ),
                end   = self._endpoint( 'g', i, 'until', birthdate ) )
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

    def _pensions( self ) -> list:
        """A pension entitlement per subject with a stated base benefit. `normal_start_age` -- the age
        the base is quoted at -- is taken from the planned start (the only age signal here); the
        engine's reduction terms for an off-normal start are deferred, so it is presently unused."""
        pensions = list()
        for m, subject in enumerate( self._subjects ):
            amount = self.cleaned_data.get( self._key( 's', m, 'penamt' ) )
            start  = self._endpoint( 's', m, 'pen_from', subject.birthdate )
            if amount is not None and start is not None:
                pensions.append( PensionEntitlement(
                    subject_handle = subject.handle, base_annual_amount = amount,
                    normal_start_age = start.year - subject.birthdate.year ) )
        return pensions

    def _merged_timing( self ) -> list:
        timing = list()
        for m, subject in enumerate( self._subjects ):
            current = self._timing.get( subject.handle ) or RetirementTiming(
                subject_handle = subject.handle )
            timing.append( replace(
                current,
                government_pension_claiming_date = self._endpoint(
                    's', m, 'ss_from', subject.birthdate ),
                pension_start = self._endpoint( 's', m, 'pen_from', subject.birthdate ) ) )
        return timing


def _at_age( birthdate : date, age : int ) -> date:
    try:
        return birthdate.replace( year = birthdate.year + age )
    except ValueError:   # 29 Feb in a non-leap target year
        return birthdate.replace( year = birthdate.year + age, day = 28 )
