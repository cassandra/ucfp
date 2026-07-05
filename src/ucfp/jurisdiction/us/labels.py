"""US-federal local terms for the neutral jurisdiction concepts (resolved via jurisdiction/labels.py).

The one place US everyday tax wording lives, so no "Roth" or "Social Security" string is hard-coded in
a shared form or template. A concept absent here simply has no US term distinct from its neutral name.
"""
from ucfp.jurisdiction.enums import JurisdictionConcept


US_LOCAL_TERMS = {
    JurisdictionConcept.GOVERNMENT_PENSION  : 'Social Security',
    JurisdictionConcept.SUBSIDIZED_HEALTH   : 'ACA',
    JurisdictionConcept.PRETAX_RETIREMENT   : '401(k) / IRA',
    JurisdictionConcept.TAX_FREE_RETIREMENT : 'Roth',
}
