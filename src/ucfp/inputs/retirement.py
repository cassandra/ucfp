"""The Retirement section: the *timing* of income and entitlements -- a plan over the income facts.

Profile > Income states the income facts (sources, amounts, the SS/pension benefit). This section owns
WHEN they happen: each *general* income flow's start/stop window (the Plans' per-flow `IncomeTiming`,
keyed by the flow's handle) and when Social Security and a pension are claimed (`RetirementTiming` per
subject). It reads the flows and entitlements from the Profile and writes only the Plans timing --
the Facts/Plans straddle the property-expenses follow (they read the Profile's properties, write only
the Plans). A rental's rent is not timed here: it runs until its property's sale event, clipped to that
date at materialize.
The date is canonical; the age beside it is a convenience `inputs.js` keeps in sync from the subject's
(fixed) birthdate.

The section is a two-column shell: the timing on the left; the right column is a placeholder for the
retirement contributions pane.
"""
from dataclasses import replace
from datetime import date
from typing import Optional

from django import forms

from ucfp.environment.constants import AppConst
from ucfp.inputs.plans.schemas import IncomeTiming, RetirementTiming
from ucfp.inputs.profile.schemas import IncomeFlow, SubjectProfile
from ucfp.inputs.widgets import IsoDateInput


class RetirementForm( forms.Form ):
    """When each income runs and each entitlement is claimed. Per general income flow (read from the
    Profile): a from/until window, with an age helper when the flow is a person's; per subject: the
    Social Security claiming and pension start dates. `apply` rebuilds the Plans' per-flow `income_timing`
    (only for the current general flows, so timing for a deleted flow self-prunes) and the per-subject
    `timing`; the Profile is untouched. Rentals are excluded -- their rent is clipped to the property's
    sale event at materialize, not timed here."""

    def __init__( self, data = None, *, profile = None, plans = None ):
        super().__init__( data )
        self._subjects = list( profile.subjects ) if profile is not None else list()
        # Only general income flows are timed here. A rental's rent is not a retirement decision: it
        # runs until the property's sale event, clipped to that date at materialize (`_clipped_to_sale`),
        # so a property-linked flow gets no window row and no `income_timing` entry.
        self._flows    = ( [ flow for flow in profile.income_flows if flow.property_handle is None ]
                           if profile is not None else list() )
        self._income_timing = { entry.flow_handle: entry
                                for entry in ( plans.income_timing if plans is not None else [] ) }
        self._timing   = { entry.subject_handle: entry
                           for entry in ( plans.timing if plans is not None else [] ) }
        # Which subjects have a pension entitlement (from the Income step) -- the pension claim line shows
        # only for them, so someone with no pension is not asked when they will start one.
        self._pensions = { pension.subject_handle
                           for pension in ( profile.pensions if profile is not None else [] ) }
        for i, flow in enumerate( self._flows ):
            self._add_window_fields( i, flow )
        for m, subject in enumerate( self._subjects ):
            self._add_entitlement_fields( m, subject )

    # --- field construction ------------------------------------------------

    def _add_window_fields( self, i : int, flow : IncomeFlow ):
        entry     = self._income_timing.get( flow.handle )
        start_on  = entry.start if entry is not None else None
        end_on    = entry.end if entry is not None else None
        birthdate = self._birthdate( flow.subject_handle )   # None for household income (no subject)
        self.fields[ self._key( 'f', i, 'from' ) ]  = self._date_field(
            start_on, f'{flow.name} income from date' )
        self.fields[ self._key( 'f', i, 'until' ) ] = self._date_field(
            end_on, f'{flow.name} income until date' )
        if birthdate is not None:
            self.fields[ self._key( 'f', i, 'from_age' ) ]  = self._age_field(
                start_on, birthdate, f'{flow.name} income from age' )
            self.fields[ self._key( 'f', i, 'until_age' ) ] = self._age_field(
                end_on, birthdate, f'{flow.name} income until age' )
            self._link_age( self._key( 'f', i, 'from' ), self._key( 'f', i, 'from_age' ), birthdate )
            self._link_age( self._key( 'f', i, 'until' ), self._key( 'f', i, 'until_age' ), birthdate )

    def _add_entitlement_fields( self, m : int, subject : SubjectProfile ):
        timing   = self._timing.get( subject.handle )
        claiming = timing.government_pension_claiming_date if timing is not None else None
        start    = timing.pension_start if timing is not None else None
        self._add_election_field( m, 'ss', 'Social Security claim', subject, claiming )
        self._add_election_field( m, 'pen', 'pension start', subject, start )

    def _add_election_field( self, m : int, kind : str, label : str, subject : SubjectProfile,
                             date_initial : Optional[ date ] ):
        self.fields[ self._key( 's', m, f'{kind}_from' ) ] = self._date_field(
            date_initial, f'{subject.name} {label} date' )
        self.fields[ self._key( 's', m, f'{kind}_from_age' ) ] = self._age_field(
            date_initial, subject.birthdate, f'{subject.name} {label} age' )
        self._link_age(
            self._key( 's', m, f'{kind}_from' ), self._key( 's', m, f'{kind}_from_age' ),
            subject.birthdate )

    @staticmethod
    def _date_field( initial : Optional[ date ], aria_label : str ) -> forms.DateField:
        """A window/election date field, labelled for assistive tech (the pane shows only a visual
        caption, so each input carries its own `aria-label`)."""
        return forms.DateField(
            required = False, initial = initial,
            widget = IsoDateInput( attrs = { 'aria-label' : aria_label } ) )

    def _age_field( self, on : Optional[ date ], birthdate : date,
                    aria_label : str ) -> forms.IntegerField:
        """The age helper beside a date, seeded from the date and labelled for assistive tech."""
        return forms.IntegerField(
            required = False, min_value = 0, max_value = 120,
            initial = self._derived_age( on, birthdate ),
            widget = forms.NumberInput( attrs = { 'aria-label' : aria_label } ) )

    def _link_age( self, date_key : str, age_key : str, birthdate : date ):
        """Tag a date/age pair so `inputs.js` keeps them in sync from the subject's fixed birthdate. The
        shared hooks come from `AppConst` so the client and this markup cannot drift."""
        shared = { f'data-{AppConst.BIRTHDATE_DATA_ATTR}' : birthdate.isoformat() }
        # The date already carries `form-control js-date` from IsoDateInput, so only add the sync
        # attributes here -- setting `class` would drop the control styling. The age is a plain
        # NumberInput, so it gets both the control class and its sync class.
        self.fields[ date_key ].widget.attrs.update(
            { f'data-{AppConst.AGE_FIELD_DATA_ATTR}' : f'id_{age_key}', **shared } )
        self.fields[ age_key ].widget.attrs.update(
            { 'class' : f'form-control {AppConst.AGE_FIELD_CLASS}',
              f'data-{AppConst.DATE_FIELD_DATA_ATTR}' : f'id_{date_key}', **shared } )

    def _birthdate( self, handle : Optional[ str ] ) -> Optional[ date ]:
        subject = next( ( s for s in self._subjects if s.handle == handle ), None )
        return subject.birthdate if subject is not None else None

    @staticmethod
    def _derived_age( on : Optional[ date ], birthdate : Optional[ date ] ) -> Optional[ int ]:
        if on is None or birthdate is None:
            return None
        return on.year - birthdate.year

    @staticmethod
    def _key( prefix : str, index : int, part : str ) -> str:
        return f'{prefix}{index}_{part}'

    # --- date-canonical resolution -----------------------------------------

    def _endpoint( self, prefix : str, index : int, part : str,
                   birthdate : Optional[ date ] ) -> Optional[ date ]:
        """A window/election date: the date is canonical; the age is a fallback for a JS-less client that
        submitted an age but no date."""
        on = self.cleaned_data.get( self._key( prefix, index, part ) )
        if on is not None:
            return on
        age = self.cleaned_data.get( self._key( prefix, index, f'{part}_age' ) )
        if age is not None and birthdate is not None:
            return _at_age( birthdate, age )
        return None

    # --- template rows -----------------------------------------------------

    @property
    def has_flows( self ) -> bool:
        return bool( self._flows )

    @property
    def subject_groups( self ) -> list:
        """The timing grouped by person -- a group per subject holding their income windows, Social
        Security claim, and (only when they have a pension) pension start -- so each person's timing reads
        as a unit rather than as scattered rows. Household income (no subject) is its own group,
        `household_income`."""
        groups = list()
        for m, subject in enumerate( self._subjects ):
            income = [ self._window_row( i, flow ) for i, flow in enumerate( self._flows )
                       if flow.subject_handle == subject.handle ]
            groups.append( {
                'subject' : subject.name,
                'income'  : income,
                'ss'      : self._election_row( m, 'ss' ),
                'pension' : self._election_row( m, 'pen' ) if subject.handle in self._pensions else None } )
        return groups

    @property
    def household_income( self ) -> list:
        """The income windows for flows with no subject (household income), shown in their own group."""
        return [ self._window_row( i, flow ) for i, flow in enumerate( self._flows )
                 if flow.subject_handle is None ]

    def _window_row( self, i : int, flow : IncomeFlow ) -> dict:
        has_age = flow.subject_handle is not None
        return { 'name'      : flow.name,
                 'from'      : self[ self._key( 'f', i, 'from' ) ],
                 'from_age'  : self[ self._key( 'f', i, 'from_age' ) ] if has_age else None,
                 'until'     : self[ self._key( 'f', i, 'until' ) ],
                 'until_age' : self[ self._key( 'f', i, 'until_age' ) ] if has_age else None }

    def _election_row( self, m : int, prefix : str ) -> dict:
        return { 'from'     : self[ self._key( 's', m, f'{prefix}_from' ) ],
                 'from_age' : self[ self._key( 's', m, f'{prefix}_from_age' ) ] }

    # --- apply -------------------------------------------------------------

    def apply( self, profile, plans ):
        return profile, replace(
            plans, income_timing = self._income_timing_out(), timing = self._merged_timing() )

    def _income_timing_out( self ) -> list:
        timing = list()
        for i, flow in enumerate( self._flows ):
            birthdate = self._birthdate( flow.subject_handle )
            timing.append( IncomeTiming(
                flow_handle = flow.handle,
                start = self._endpoint( 'f', i, 'from', birthdate ),
                end   = self._endpoint( 'f', i, 'until', birthdate ) ) )
        return timing

    def _merged_timing( self ) -> list:
        timing = list()
        for m, subject in enumerate( self._subjects ):
            current = self._timing.get( subject.handle ) or RetirementTiming(
                subject_handle = subject.handle )
            timing.append( replace(
                current,
                government_pension_claiming_date = self._endpoint( 's', m, 'ss_from', subject.birthdate ),
                pension_start = self._endpoint( 's', m, 'pen_from', subject.birthdate ) ) )
        return timing


def _at_age( birthdate : date, age : int ) -> date:
    try:
        return birthdate.replace( year = birthdate.year + age )
    except ValueError:   # 29 Feb in a non-leap target year
        return birthdate.replace( year = birthdate.year + age, day = 28 )
