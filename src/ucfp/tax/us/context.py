"""The US taxpayer context -- the `tax_context` the US federal engine consumes.

US-shaped (filing status, ACA), so it lives in the US package. The Scenario
resolves it per interval (ages from birthdates, post-event filing status). A neutral
taxpayer seam can be extracted if a second jurisdiction is added.

NOTE: stub -- fields (filing status, household size, state, ACA enrollment,
per-subject ages/blindness) are added as the engine's stages land.
"""


class TaxContext:
    pass
