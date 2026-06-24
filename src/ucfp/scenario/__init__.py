"""The user's planning assumptions -- the discretionary "what if" knobs.

The second half of a forecast's user-facing inputs (the first is `ucfp.profile`); together
they materialize into the engine's `ForecastParameters`. This half holds what the user
*chooses* rather than what is determined for them: anything they would vary to explore an
outcome. These inputs carry sensible defaults and are saved as many labeled variants -- a
user keeps multiple named scenarios over one fixed set of facts and compares them. (Unlike
a profile, having more than one scenario is a first-class, user-visible concept.)

Two kinds of assumption, grouped accordingly:

  External factors (exogenous -- about the world, not the user):
    - Economic outlook -- inflation, wage growth, per-class appreciation/dividend/interest,
                          retirement growth, pension & SS COLAs, rental increase.
    - Tax projection   -- how current tax law is carried forward (the law itself is
                          admin-curated).

  Personal choices (the levers a user turns):
    - Timing        -- retirement date; SS claiming age / pension start date; salary stop.
                       Date knobs select into `profile` entitlement facts, so the realized
                       benefit is derived by the engine, never stored here.
    - Lifestyle     -- the high/medium/low spending schedule over time; discretionary
                       category amounts.
    - Saving        -- retirement contributions: amount, source, duration.
    - Drawdown      -- cash floor/ceiling; draw order; sweep allocation.
    - Planned moves -- Roth-conversion timing/amount; large purchases; gifts in/out.
    - Life events   -- assumed death timing; health-coverage assumptions.

Stub: the sections above are the intended shape; models are deferred to drill-down.
"""
