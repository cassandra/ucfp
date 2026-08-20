"""Template tags for organization-aware UI composed into other apps' pages.

The Account page (in the user app) renders its household/account deletion
controls through ``household_danger_section`` so the user app never imports
organization code -- the composition is at the template layer only.
"""
from django import template

from organization.models import OrganizationMember

register = template.Library()


@register.inclusion_tag('organization/_danger_section.html')
def household_danger_section(user):
    """Render the Account page "Danger" section for ``user``.

    Inert (renders nothing) when there is no authenticated user with memberships.
    Otherwise it classifies each active membership so the template can offer the
    right control (delete the household, or leave it) and disclose exactly what
    deleting the account would destroy versus leave. The self-hosted Guest is a
    normal owner here, so it too sees the delete control -- a legitimate "reset all
    my data" (the identity middleware re-provisions a fresh household afterward).
    """
    if ( user is None ) or ( not user.is_authenticated ):
        return { 'show': False }

    memberships = list(
        OrganizationMember.objects.for_user( user ).select_related( 'organization' ) )
    if not memberships:
        return { 'show': False }

    rows = []
    for member in memberships:
        rows.append( {
            'organization' : member.organization,
            'role_label'   : member.organization_role.label,
            'can_delete'   : member.is_active_owner,
        } )

    return {
        'show'  : True,
        'rows'  : rows,
        # The common case -- sole owner of a single household -- collapses to one
        # "Delete my account and all my data" control.
        'simple': ( len( memberships ) == 1 ) and memberships[ 0 ].is_sole_active_owner,
    }


@register.inclusion_tag( 'organization/_switcher.html', takes_context = True )
def organization_switcher( context ):
    """Render the navbar's current-household indicator, and a switcher when the user has more
    than one household.

    Inert (renders nothing) without an authenticated user and a resolved current organization --
    both are present on every app page (``ensure_organization`` sets ``request.organization``). The
    current household is always shown for context; the other households the user actively belongs to
    are offered as switch targets, so the control only becomes a menu once there is somewhere to
    switch to.
    """
    request = context.get( 'request' )
    user    = getattr( request, 'user', None )
    current = getattr( request, 'organization', None )
    if ( request is None ) or ( user is None ) or ( not user.is_authenticated ) or ( current is None ):
        return { 'show': False }

    memberships = OrganizationMember.objects.for_user( user ).select_related( 'organization' )
    other_organizations = [ membership.organization for membership in memberships
                            if membership.organization_id != current.pk ]
    return {
        'show'                : True,
        'current'             : current,
        'other_organizations' : other_organizations,
        'has_others'          : bool( other_organizations ),
    }
