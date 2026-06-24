"""The user's financial facts -- their committed, observed current situation.

One of the two halves of a forecast's user-facing inputs (the other is `ucfp.scenario`);
together they materialize into the engine's `ForecastParameters`. This half holds what is
*determined* for the user -- observed now or contractually committed -- as opposed to the
discretionary assumptions a user varies in a "what if". The operative test: if you would
not vary it to explore an outcome, it is a fact and belongs here.

Facts carry no defaults (an absent fact is missing data, not a sensible guess), resolve at
monthly granularity (forecasts run as fine as monthly), and change only by correction,
added detail, or the passage of time. A user normally sees a single latest profile: an
edit overwrites within the current month and otherwise copies the latest forward into a
new month, so history accrues automatically while only the latest is shown. (Named profile
*variations* are a later, advanced capability; the design must not assume one profile per
user.)

Sections (provisional, pending drill-down):
  - People               -- each subject's birthdate; household filing status.
  - What you own         -- holdings: opening value, cost basis, class, owner; cash balance.
  - What you owe         -- loans: opening balance, rate, term (the contract).
  - Income entitlements  -- current salary level; pension terms; a government pension (the
                            state retirement benefit at normal retirement age, e.g. US Social
                            Security). These are *entitlement facts*, not realized streams: a
                            benefit is a function of a date knob held in `scenario`, composed
                            with the jurisdiction's adjustment schedule (`tax.government_pension`).
  - Committed obligations-- non-loan committed outflows: rent, premiums, tuition, property
                            tax.

Several domains straddle the fact/assumption seam -- a loan's contract is a fact while
extra principal is a `scenario` strategy; income's current level is a fact while its growth
and timing are `scenario` knobs. This package holds only the fact side of each.

Stub: the sections above are the intended shape; models are deferred to drill-down.
"""
