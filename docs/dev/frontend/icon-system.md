# Icon System

## Overview

Use the standardized `{% icon %}` template tag for consistent icon rendering.
The tag and the available icons live in `common/templatetags/icons.py`; the
styling lives in the icon-system section of `src/ucfp/static/css/main.css`
(the `.icon` base class plus `.icon-<size>` and `.icon-<color>` classes).

```django
{% load icons %}
{% icon "plus" size="md" color="primary" aria_label="Add item" %}
```

## UX Principles for Icon Usage

### Primary Value
Icons provide faster recognition, a universal language, space efficiency, and visual hierarchy.

### ALWAYS Add Icons When
- **Universal Actions**: Add (+), Delete (trash), Edit (pencil), Save (check), Cancel (x)
- **Navigation**: Back/Forward, Up/Down, Expand/Collapse
- **Status/Feedback**: Success, Warning, Error, Info

### Key Design Principle
Focus on **ACTION TYPE** (add, delete, edit), not object specificity. "Add Item"
and "Add Rule" both get the same `+` icon because they are both "add" actions.

## The `{% icon %}` Tag

```
{% icon name size="md" color=None aria_label=None title=None css_class="" %}
```

### Size Options
The `size` argument maps to an `.icon-<size>` class:
- `sm` - small
- `md` - default
- `lg` - large
- `xl` - extra large
- `xxl`, `xxxl` - larger fixed sizes
- `fluid` - scales to its container

An unrecognized size falls back to `md`.

### Color Options
The `color` argument maps to an `.icon-<color>` class drawn from `ICON_COLORS`
(the project's semantic palette, e.g. `primary`, `success`, `warning`, `danger`,
`muted`). Omit it to inherit the surrounding text color. An unrecognized color
is ignored.

### Other Arguments
- `aria_label` - accessible label; **required for icon-only controls**.
- `title` - native tooltip text.
- `css_class` - extra classes appended to the icon (e.g. Bootstrap spacing
  utilities like `mr-1` to separate an icon from adjacent text).

## Template Usage Examples

### Action Buttons
```django
{% load icons %}

<button class="btn btn-primary">
  {% icon "plus" size="sm" css_class="mr-1" %}
  Add New Item
</button>

<button class="btn btn-success" type="submit">
  {% icon "save" size="sm" css_class="mr-1" %}
  Save Changes
</button>
```

### Icon-Only Actions (require an aria-label)
```django
<button class="btn btn-danger btn-sm" aria-label="Delete item">
  {% icon "delete" size="sm" aria_label="Delete item" %}
</button>

<button type="button" class="close" data-dismiss="modal" aria-label="Close">
  {% icon "close" size="sm" aria_label="Close" %}
</button>
```

### Status and Feedback
```django
<div class="alert alert-success">
  {% icon "check-circle" size="sm" color="success" css_class="mr-1" %}
  Operation completed successfully.
</div>
```

## Accessibility

- Always pass `aria_label` for icon-only controls.
- Icons should supplement text for important actions, not replace it.
- Ensure icon buttons have a visible focus indicator (see
  [Style Guidelines](style-guidelines.md)).

## Icon Discovery

- `{% icon_list %}` renders the set of available icon names.
- The `has_icon` filter tests availability: `{% if "plus"|has_icon %}...{% endif %}`.

When an action needs an icon, prefer an existing one whose visual matches the
action type; add a new SVG to the icon set only when nothing fits.

## Related Documentation
- Frontend guidelines: [Frontend Guidelines](frontend-guidelines.md)
- Style guidelines: [Style Guidelines](style-guidelines.md)
- Template conventions: [Template Conventions](template-conventions.md)
