---
allowed-tools: Bash, Read, Write, Edit, Grep, TodoWrite
description: Find existing icons or create new ones for the standardized icon system
argument-hint: [concept/action]
---

Find or create an icon for "$0":

## Icon Discovery and Creation Process

Find the best existing icon, or create a new one if none fits:

1. **Use TodoWrite to plan the icon workflow** - Track discovery and creation steps.

2. **Search existing icons first** - always prefer an existing icon for consistency:
   - Read `AVAILABLE_ICONS` in `src/common/templatetags/icons.py` (or run `{% icon_list %}` / call `has_icon(name)`).
   - Browse the SVGs in `src/common/templates/icons/`.
   - Look for semantic matches and universal conventions.

3. **Analyze the results** - determine the best match, or the need for a new icon.

4. **Recommend an existing icon OR create a new one** - based on the search.

## Step 1: Search

**Searching for concept**: "$0"

### Semantic Matching Strategy
Match on the action type, not the object:
- **Action synonyms**: Add/Create/New -> `plus`; Edit/Modify -> `edit`; Delete/Remove -> `delete`; Save/Submit/Confirm -> `save` or `check-circle`; Cancel/Close -> `cancel` or `close`.
- **Universal conventions**: Settings -> `settings`; Help -> `question-circle`; Alert -> `warning`; Success -> `check-circle`.
- **Navigation**: Back -> `chevron-left`; Forward -> `chevron-right`; Up/Down -> `chevron-up` / `chevron-down`.

(Confirm the exact names against `AVAILABLE_ICONS` -- the set is the union of the SVGs shipped under `common/templates/icons/`.)

## Step 2: Decision - Use Existing or Create New

### IF a good match is found
**Recommendation**: use the existing icon `[icon-name]`.

**Usage**:
```django
{% load icons %}
{% icon "[icon-name]" size="sm" color="primary" css_class="mr-1" %}
```
(`size` maps to `.icon-<size>`, `color` to `.icon-<color>`; `css_class` is for extra classes such as Bootstrap spacing. Pass `aria_label` for icon-only controls.)

**Rationale**: [why this icon matches the concept]

### IF no good match
**Recommendation**: create a new icon `[proposed-name]`.

**Rationale**: no existing icon adequately represents "$0" because [specific gap].

## Step 3: Create a New Icon (if needed)

**1. Create the SVG template** at `src/common/templates/icons/[new-icon-name].svg`, mirroring the shape of the existing icons:
```django
<svg class="{{ class_attr }}" viewBox="0 0 24 24" fill="currentColor" {{ accessibility_attrs }}>
  <path d="[SVG PATH DATA]"/>
</svg>
```
**Requirements:**
- `viewBox` MUST be `0 0 24 24`.
- Use `fill="currentColor"` so CSS color (the `.icon-<color>` class) is inherited.
- Keep `{{ class_attr }}` and `{{ accessibility_attrs }}` (the `icon` tag injects them).
- Simple, optimized single-color paths; no transforms, groups, or extra attributes.

**2. Register the name** in `AVAILABLE_ICONS` in `src/common/templatetags/icons.py` (add it alphabetically).

**3. Verify** the icon renders at the relevant sizes/colors (e.g. on a `/testing/ui/` page).

## Icon Philosophy

1. **Search first** - reuse for consistency.
2. **Don't compromise** - add a new icon when nothing fits.
3. **Action-focused** - icons represent actions/concepts, not specific objects.
4. **Semantic naming** - actions are verb/verb-noun (`edit`, `delete`); status is state-shape (`check-circle`, `warning`); directional is direction-shape (`chevron-up`).

**Concept to find/create**: "$0"

Begin icon discovery and recommendation now.
