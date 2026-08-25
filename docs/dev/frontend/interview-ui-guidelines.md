# Interview Input UI Guidelines

The visual language and interaction rules for the interview input pages under
`/inputs/interview/*` -- the Profile, Plans, and Assumptions flows. These pages
grew up independently and converged only loosely; this document establishes the
one language they should all speak, so a pattern learned on one page carries to
the next.

It is the authoritative source for *how input sections look and behave*. It sits
alongside, and defers to, the general
[Frontend Guidelines](frontend-guidelines.md),
[Style Guidelines](style-guidelines.md), and
[Template Conventions](template-conventions.md) -- nothing here overrides those;
it specializes them for the interview surface.

## Status

Release-hardening, UI-polish work (see
[project-phase.md](../project/project-phase.md)). The primitives below are the
*target*: they are built and adopted page by page, not all at once. Where a
section has not yet migrated, it is expected to look like its old self until its
turn -- consistency is reached by convergence, not by a flag day.

## Two content families

Every interview section is one of two shapes. Name which one a section is before
styling it; the rules differ.

1. **Collections** -- a variable-length set of like things the user builds up:
   vehicles, debts, properties, events, contributions, income lines. The user
   adds, edits, and removes members.
2. **Scalar fields** -- a fixed set of labeled inputs: account balances, economic
   factors, sale costs, cash bands. Nothing is added or removed; the user just
   fills boxes.

Collections are where the drift lives, and where most of this document applies.
The scalar-field sections are already consistent; their job here is to stay that
way (see [Frozen exemplars](#frozen-exemplars)).

## Collections: one pattern

Historically collections used four different interaction models -- an editor
opened *below* the list (Vehicles, Debts), an editor to the *right* (Money
movements), a self-spawning blank table row (Income, Possessions), and a
self-spawning blank form block (contributions, tax planning). We consolidate all
four onto one:

### Layout: list-left / editor-right

- The collection is **two columns**: the list of members on the left, a single
  editor slot on the right.
- **Side by side at `md` and up** (the primary tablet-landscape target); stacked
  to one column below `md` (phone landscape), list above editor. The exact
  breakpoint is tunable per page where an editor is unusually wide, but `md` is
  the default -- do not silently follow the older `col-lg` split, which collapses
  the two columns on the primary target.
- The editor slot is empty until the user adds or edits; opening one does not
  reflow the list.

### Add / edit lifecycle -- explicit, never phantom

- **Add** is an explicit control (a single "Add ..." button, or -- for a typed
  collection -- a control that opens the editor with a type choice inside it). It
  opens a blank `input-editor-card` in the editor slot.
- **Edit** on a member opens that member's editor in the same slot.
- **Done / Save** commits and closes the editor; **Cancel / close** discards and
  closes. Only one editor is open at a time; the member being edited shows the
  active state.
- **Retire the self-spawning blank row and blank block.** A collection never grows
  by the user filling a phantom trailing row. Adding is always a deliberate act
  with a real open/close lifecycle.
- When the editor opens on a stacked (phone) layout, it must scroll into view and
  take focus, so "Add"/"Edit" is not a no-op below the fold.

## The primitives

Four shared components carry the pattern. Each is a real, named component with BEM
classes in `main.css` -- **not** a per-section assembly of Bootstrap utilities.
This is the rule that keeps the pages from re-diverging: a refinement to a
primitive lands everywhere at once, and there is exactly one place to make it.
Primitive names are prefixed `input-` to scope them to this surface and avoid
collision as the app grows.

### `input-item-card`

One member of a collection, in the left list.

- Structure: an optional **badge** (`__badge`), the **title** (`__title`), inline
  **headline** facts (`__headline`), right-aligned **actions** (`__actions`:
  Edit, Remove), and an optional muted **detail** line beneath (`__detail`).
- States: `--active` (this member's editor is open) renders the one canonical
  editing affordance -- a left accent border and subtle fill; `--readonly` (a
  member owned by another section, e.g. a mortgage shown in Debts) drops the
  actions and shows a pointer to its home section instead.
- Actions are touch targets: Edit and Remove must meet the 44px minimum -- the
  current bare text links and `×` glyphs do not, and this is the primitive's job
  to fix.

### `input-editor-card`

The open form for adding or editing one member, in the right slot.

- Structure: a **header** (`__header`: title + a close control `__close`), a
  **body** of fields (`__body`), and a **footer** of actions (`__footer`:
  Done/Save, Cancel).
- One editor open at a time. Replaces the ad-hoc `card`+header, the custom
  `property-editor`, and the inline blocks used today.

### `input-disclosure`

A gate that keeps an optional sub-form collapsed until the user affirms it exists
-- an auto loan on a vehicle, a mortgage on a home, a pension for a person.

- **Realized by the existing `js-optional` mechanism** (inputs.js): a `js-optional`
  wrapper, a `js-optional-body` of fields, and a control that reveals the body and
  clears it on dismiss -- so the server infers "absent" straight from empty fields
  (no stored "include this?" flag). Two control styles share the one mechanism:
  - a **toggle checkbox** (`js-optional-toggle`) that asks the question explicitly
    ("This vehicle has a loan") -- the **preferred** form for a single binary
    optional, since it frames the decision; and
  - the older **add/remove buttons** (`js-optional-add` / `js-optional-remove`),
    still used by the People partner block, to be converged onto the checkbox.
- The body auto-opens on load when its fields are already filled (editing an
  existing loan), so the gate reflects reality without a stored flag.
- Replaces today's always-rendered optional blocks, which show a full empty
  loan/mortgage/pension form to users who have none.

### `input-age-band`

The recurring "when" control -- `From [age] on [date] ... Until [age] on [date]`
-- used by retirement timing, tax-planning schedules, and expense "until age".

- One aligned component so the age and date inputs line up everywhere, instead of
  the free-floating, aligned-to-nothing inputs on those pages today.

## Contracts every primitive honors

Beyond looks, each primitive lives inside the app's async machinery and must
respect these, or a redesign silently breaks behavior:

- **Named CSS, BEM, in `main.css`.** `.input-item-card`,
  `.input-item-card__actions`, `.input-item-card--active`, and so on. Extend
  Bootstrap; do not re-implement it. No CSS in templates.
- **Async swap-target id contract.** Each collection swaps by element id through
  `antinode` -- a stable **list** target and a stable **editor-slot** target
  (today `debts-list` / `debt-form`, etc.). Follow a `{collection}-list` /
  `{collection}-editor` convention. Any id or class name that JavaScript also
  references is defined once in `AppConst` (`constants.py`) per the
  client-server namespace rule in the Frontend Guidelines -- never duplicated as a
  literal on both sides.
- **Read-only / edit-only.** Every section renders in a read-only mode (the
  example-data tour, and any non-editable viewer). Primitives take an `editable`
  flag and drop Add/Edit/Remove when false; do not bolt this on afterward.
- **Responsive & touch.** `md`+ two-column, stack below; 44px touch targets;
  16px minimum control font; visible focus. See [Style Guidelines](style-guidelines.md).

## Tables: keep the table, fix the lifecycle

Some collections are homogeneous scalar rows and read better as a table than as a
card list -- Income and Possessions. For these:

- **Keep the table layout.** It is fine and sometimes clearer than cards.
- **Replace the phantom trailing row** with the explicit-add `js-rowset` primitive
  (constants + inputs.js): a `js-rowset` table body holds the rows; a hidden
  `<template>` prototype is cloned into it by the Add button, and each row carries
  a **Remove**. The rows use repeated same-name inputs the form reads as parallel
  lists (`getlist`) -- no per-row index to keep in sync, so client add/remove is
  clean. No self-spawning blank row, no "fill the blank row to add one".
- Rows that are **fixed** (a person's Social Security and pension lines, each
  rental's rent) stay pinned, amount-only, and non-removable; only user-added rows
  carry Add/Remove. Put the **fixed rows on top** so appended rows land at the
  bottom and never wedge between fixed ones.
- **Remove is the danger-text "Remove"** (as on the cards), not a bare "×" --
  reserve "×" for close/collapse. Keep the deletion control the same word
  everywhere.
- A money amount in a hand-rendered row uses the `_money_cell.html` partial (the
  `$` affix + `js-money` hook), and its posted value is parsed back through a
  `MoneyField`, so the money "shape" is not re-implemented.

## Frozen exemplars

These are already consistent and correct. Copy them; do not reinvent them, and do
not let a redesign churn them.

- **Scalar grid** -- Accounts, via `_field_row.html` (input-left, label-right).
  The reference for any two-column number grid.
- **Factor list** -- Economics, Sales, Net Worth: label + `$`/`%`-adorned input +
  a muted helper line. The reference for a list of tuned rates/amounts.
- **The `$` / `%` input adornment** -- the grey prefixed `$` and suffixed `%`.
  This is the one primitive the interview already shares consistently.
  Standardize *onto* it; leave it alone.
- **The draw-order ranked list** -- Cash management's reorderable, annotated list
  is a legitimate bespoke control; it is not a collection to normalize.

## Intentional -- do not "normalize" these away

Some cross-page differences are deliberate and must survive a consistency pass:

- **Yellow `Next` vs. blue `Next`/`Finish`.** `btn-cta` (yellow) shows while the
  flow is incomplete; `btn-primary` (blue) once complete. Driven by
  `current_flow_complete` in `section.html`. It is a completion signal, not drift.
- **Profile default width vs. Plans/Assumptions `container-fluid`.** Plans and
  Assumptions go full width for their wide age-band matrices; Profile stays
  default because it has no such content. Keep per-flow.
- **Section badges** (ownership, "entered in ...", "needs details") are meaningful
  status, not decoration.

## Page-structure decisions

Separate from styling, two overloaded pages split, and several optional blocks
become disclosure gates:

- **Retirement -> Retirement + Contributions.** Income timing and benefit claiming
  stay on Retirement; recurring contributions move to their own section.
- **Vehicle plan -> Vehicle plan + Vehicle expenses.** Per-vehicle running costs
  move to their own section, which hides itself (with a message) when there are no
  vehicles.
- **Home & Property split is deferred** -- decide after the primitives (especially
  the disclosure gate on the mortgage and the fixed rental long-form) are applied,
  since they may remove the reason to split.
- **Disclosure gates:** the home mortgage, each vehicle's auto loan, and each
  person's pension are gated -- shown only when the user has one.

These change the stepper and flow, not just markup; sequence them as their own
steps, not folded into a styling migration.

## Migration process (per page)

Each section migrates on its own, in this order:

1. **Define the plan first.** A short written plan for the section -- what
   archetype it is, which primitives it uses, what changes -- before any code. An
   issue is optional for a small section; a larger one (a page split) warrants one.
2. **Implement** with the primitives above; no new per-section utility soup.
3. **Review** -- `/review` with the `test-engineer` and `frontend-dev` agents,
   `make check` green (lint + test + env-drift).
4. **Iterate** on the visuals in place (the CSS is one primitive, so refinements
   are cheap and global).

**Sequencing: a sampler first, then a sweep.** Build and harden the primitives on
one reference page per distinct archetype before rolling out:

- **Debts** -- the reference for the list + editor pattern (it exercises
  `input-item-card` -- including its read-only "entered in ..." variant and the
  active state -- and `input-editor-card`, in one page). Its loan-terms reveal is
  a *kind switch*, not the disclosure gate, so Debts does not exercise
  `input-disclosure`. Then **Vehicles** confirms the primitives hold with an
  ownership badge and introduces `input-disclosure` (the auto-loan gate).
- **Income** -- the reference for the table + explicit-lifecycle pattern (fixed
  rows plus added rows).

Once the primitives are proven on the sampler, the remaining collection pages are
mostly mechanical application.

## Related documentation

- [Frontend Guidelines](frontend-guidelines.md)
- [Style Guidelines](style-guidelines.md)
- [Template Conventions](template-conventions.md)
- [Icon System](icon-system.md)
