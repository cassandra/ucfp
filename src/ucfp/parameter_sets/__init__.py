"""The curated parameter-set library -- the admin-managed source of reasonable defaults.

Holds the system defaults (e.g. baseline / conservative / optimistic economic outlooks) as
`ParameterSet` records, seeded from canonical code-defined values by the `seed_parameter_sets`
command and read from the database at runtime so an admin can adjust them. A scenario chooses a
set by name; the planning layer loads it at materialization.

Payloads are schedule-shaped from the start (a value that varies over time is a list of windowed
segments, never a lone instance), since the engine takes schedules throughout. Organization-owned
copies and the system->user override cascade are a later phase; the seed's modify-vs-refresh
lifecycle already establishes that pattern one layer up (canonical -> system default).
"""
