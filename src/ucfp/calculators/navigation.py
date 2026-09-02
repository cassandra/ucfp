"""The login-free (publicly reachable) calculators, in nav order.

A single source of truth for *which* calculators an anonymous visitor may use and *how* to link to them.
Consumed today by the anonymous app-shell navbar (`pages/_public_navbar_menu.html`); when a second
calculator ships it will also feed the signed-in calculators dropdown, so both surfaces stay in step.
Adding a public calculator is a one-line entry here -- plus exempting its route namespace in the
authentication middleware, which is what actually makes it reachable while signed out.
"""
from typing import NamedTuple


class PublicCalculator( NamedTuple ):
    """A login-free calculator's nav entry: the menu label, the URL name its link targets, and the
    resolver namespace used to light the link while the visitor is on that calculator."""
    label     : str
    url_name  : str
    namespace : str


PUBLIC_CALCULATORS = [
    PublicCalculator(
        label     = 'Social Security Timing',
        url_name  = 'calculators:ss_timing:inputs',
        namespace = 'calculators:ss_timing' ),
]
