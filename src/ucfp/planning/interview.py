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

from ucfp.profile.schemas import (
    PARTNER_SUBJECT_HANDLE, PRIMARY_SUBJECT_HANDLE, Profile, SubjectProfile )
from ucfp.scenario.schemas import RetirementTiming, Scenario
from ucfp.tax.enums import FilingStatus


class Aggregate( Enum ):
    """Which typed aggregate a section reads from and writes to -- the canonical discriminator the
    section spine and the persistence dispatch share, so neither side spells out a bare string."""
    PROFILE  = auto()
    SCENARIO = auto()


@dataclass( frozen = True )
class Section:
    """One step of the interview: a stable `key` (its URL segment), a user-facing `title`, the
    `aggregate` it edits, and the `form` that drives it (None until the section is built)."""
    key: str
    title: str
    aggregate: Aggregate = Aggregate.PROFILE
    form: Optional[ type ] = None


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

    def apply_to( self, profile : Profile ) -> Profile:
        return replace(
            profile, subjects = self._subjects(), filing_status = self._filing_status() )

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

    def apply_to( self, scenario : Scenario ) -> Scenario:
        return replace( scenario, timing = self._merged_timing() )

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


# The interview's order, from the input model in issue #4. A section with a form is live; the rest
# are declared so the stepper shows the full path ahead.
SECTIONS = [
    Section( 'subjects'    , 'Who this plan is for', form = SubjectsForm ),
    Section( 'retirement'  , 'Retirement timing', Aggregate.SCENARIO, RetirementForm ),
    Section( 'home'        , 'Home' ),
    Section( 'accounts'    , 'Accounts' ),
    Section( 'income'      , 'Income' ),
    Section( 'spending'    , 'Spending' ),
    Section( 'events'      , 'Plans & events' ),
    Section( 'assumptions' , 'Assumptions' ),
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
