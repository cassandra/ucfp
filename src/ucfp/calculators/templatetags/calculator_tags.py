"""Template helpers for the calculators app."""
from django import template

from ucfp.calculators.navigation import PUBLIC_CALCULATORS

register = template.Library()


@register.simple_tag
def public_calculators():
    """The login-free calculators, in nav order -- for the anonymous app-shell navbar (and, later, the
    signed-in calculators dropdown). See `ucfp.calculators.navigation`."""
    return PUBLIC_CALCULATORS
