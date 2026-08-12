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

    Inert (renders nothing) when there is no authenticated user with memberships
    -- e.g. under suppressed authentication, where the shared organization is
    memberless. Otherwise it classifies each active membership so the template
    can offer the right control (delete the household, or leave it) and disclose
    exactly what deleting the account would destroy versus leave.
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
