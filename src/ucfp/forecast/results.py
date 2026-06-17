"""Outputs of a Period computation."""


class Notice:
    """A notable occurrence raised during a Period -- a forced draw, an RMD taken,
    an asset sold, savings depleted, a lifestyle-band change. This is the
    planning-insight stream the Forecast accumulates and surfaces to the user, and
    is distinct from the *input* money-movement events: a Notice is what actually
    happened.

    NOTE: stub -- shape (kind + payload, link to the realizing transaction) TBD.
    """


class PeriodResult:
    """What a Period produces: the notices it raised and the period's outcome
    (e.g. whether the stop condition was hit). The generated transactions live in
    the Ledger the Period posted to.

    NOTE: stub -- fields TBD.
    """
