"""User-facing planning orchestration -- the layer above profile, plans, and the engine.

It materializes a `Profile` + `Plans` + `Assumptions` + run frame into the engine's
`ForecastParameters` (`materialization.py`), runs the forecast, and captures the inputs and
outputs together as an immutable record for reporting and drill-down. No input app depends on
another, and the engine must not depend on any; this layer composes them, so the composition
lives here rather than coupling the peers or inverting the engine's layering.
"""
