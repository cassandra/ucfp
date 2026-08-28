# Performance Profiling Commands

Two management commands profile the forecast subsystem so a change is measured, not
guessed (the "measure before optimizing" rule). Both replay a real captured run from
the dev database and are read-only.

Run them from `src/`:

```bash
cd src && ./manage.py profile_run       [<run-uuid>] [-n N] [--lens default|expanded|both] [--no-render]
cd src && ./manage.py profile_forecast  [<run-uuid>] [-n N] [--granularity year|quarter|month] [--top N]
```

Both default to the most recently captured run when no uuid is given.

## `profile_run` -- the results *display* path

Profiles what `RunResultsView` does to turn a stored run into the `/run/{uuid}` page:
deserialize the run, reload its books, build the column table, the outcome summary, the
balances sparkline, and render the table fragment. Reports **per-stage min/median wall
time and SQL query counts** over several iterations, for the default column lens and the
fully-expanded worst case.

Use it when working on **display / table-browsing performance** -- the results page, the
books-table column operations (expand/collapse/hide/reorder), or the charts. It isolates
the display cost from the engine, and the per-stage query counts surface N+1s.

## `profile_forecast` -- the *run* (compute + capture) path

Profiles what `run_and_capture` does when a user runs a forecast: materialize the inputs
into engine parameters, run the pure `Forecast` engine, stamp display placements, and
persist the books. Reports **per-phase timing and query counts**, and **cProfiles the
pure engine** to surface its hottest functions. The persist phase runs inside a
rolled-back transaction, so profiling writes nothing.

Use it when working on **forecast run performance** -- the engine compute or the capture
(persist) cost. `--granularity` re-runs at a different period count (yearly/quarterly/
monthly) to see how the engine scales; `--top` sets how many hot functions to list.

## Reading the output

- **Query counts** are the signal for round-trip cost (what dominates on a constrained
  host); a count that grows with the run's size is an N+1.
- **Wall time** is min/median over the iterations; the first (warm-up) pass is discarded.
- Pair a change with a before/after run of the relevant command, and prefer a
  **regression test** (e.g. an `assertNumQueries`-style guard) for anything worth keeping
  fixed -- the commands are for investigation, the tests are the durable guard.
