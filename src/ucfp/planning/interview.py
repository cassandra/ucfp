"""The guided interview that builds a plan's initial inputs.

The interview is one *sequential* view over the same `Profile` (and, later, `Scenario`)
aggregates the free-form edit pages own: a first-time user is walked section by section to
populate them, then edits them directly afterward for surgical changes. This module defines the
section spine -- the ordered steps and their titles, the single source of the interview's order --
and the per-section forms that map input onto the typed aggregates.

Only §1 (subjects) is built so far; the rest are declared so the stepper shows the whole path, and
a new section becomes live simply by adding its form to `SECTION_FORMS`.
"""
from dataclasses import dataclass, replace
from typing import Optional

from django import forms

from ucfp.profile.schemas import Profile, SubjectProfile
from ucfp.tax.enums import FilingStatus


@dataclass( frozen = True )
class Section:
    """One step of the interview: a stable `key` (used in the URL and the form registry) and a
    user-facing `title`."""
    key: str
    title: str


# The interview's order, from the input model in issue #4. A section is *implemented* once it has
# a form in `SECTION_FORMS`; the rest are declared so the stepper shows the full path ahead.
SECTIONS = [
    Section( 'subjects'    , 'Who this plan is for' ),
    Section( 'retirement'  , 'Retirement timing' ),
    Section( 'home'        , 'Home' ),
    Section( 'accounts'    , 'Accounts' ),
    Section( 'income'      , 'Income' ),
    Section( 'spending'    , 'Spending' ),
    Section( 'events'      , 'Plans & events' ),
    Section( 'assumptions' , 'Assumptions' ),
]


class SubjectsForm( forms.Form ):
    """§1 -- who the plan is for. Collects one subject, optionally a partner, and *infers* the
    filing status (joint when there is a partner) rather than asking it; the inferred status stays
    editable later in the edit views. `apply_to` writes just this section onto the Profile, leaving
    every other section's facts intact.
    """

    _PRIMARY_HANDLE = 'subject'
    _PARTNER_HANDLE = 'partner'

    subject_name      = forms.CharField( label = 'Name', max_length = 100 )
    subject_birthdate = forms.DateField( label = 'Birthdate' )
    has_partner       = forms.BooleanField(
        label = 'This plan includes a partner', required = False )
    partner_name      = forms.CharField( label = 'Partner name', max_length = 100, required = False )
    partner_birthdate = forms.DateField( label = 'Partner birthdate', required = False )

    def __init__( self, data = None, profile : Profile = None ):
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
            handle = self._PRIMARY_HANDLE,
            name = cleaned[ 'subject_name' ], birthdate = cleaned[ 'subject_birthdate' ] ) ]
        if cleaned.get( 'has_partner' ):
            subjects.append( SubjectProfile(
                handle = self._PARTNER_HANDLE,
                name = cleaned[ 'partner_name' ], birthdate = cleaned[ 'partner_birthdate' ] ) )
        return subjects

    def _filing_status( self ) -> FilingStatus:
        has_partner = self.cleaned_data.get( 'has_partner' )
        return FilingStatus.MARRIED_JOINT if has_partner else FilingStatus.SINGLE


# A section is live once it appears here, mapping its key to the form that drives it.
SECTION_FORMS = {
    'subjects': SubjectsForm,
}


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
    following = keys[ keys.index( key ) + 1 : ] if key in keys else []
    live      = ( section_for( candidate ) for candidate in following if candidate in SECTION_FORMS )
    return next( live, None )
