"""User-facing planning orchestration -- the layer above profile, scenario, and the engine.

Spans all three: it materializes a `Profile` + `Scenario` + run frame into the engine's
`ForecastParameters` (`materialization.py`), runs the forecast, and (next) captures the
inputs and outputs together as an immutable record for reporting and drill-down. Neither
`profile` nor `scenario` depends on the other, and the engine must not depend on either;
this layer composes them, so the composition lives here rather than coupling the two peers
or inverting the engine's layering.
"""
