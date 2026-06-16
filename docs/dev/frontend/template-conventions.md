# Template Conventions

## Checklist

- [ ] Template names referenced in views closely match the view names that use them.
- [ ] No templates have in-line Javascript.
- [ ] No templates have in-line CSS.
- [ ] Templates appear in a subdirectory matching their purpose: modals, panes, pages.
- [ ] Template tag `load` statements are near the top of the file.

## Template Directory Structure

Each app keeps its templates namespaced under the app name (apps are top-level
siblings under `src/`; see [Project Structure](../shared/project-structure.md)):

```
<app>/templates/<app>/
├── pages/          # Full HTML pages
├── modals/         # Modal dialogs
├── panes/          # Page fragments
├── email/          # Email templates
├── svg/            # SVG files
└── edit/           # Edit-mode templates (mirrors pages/ modals/ panes/)
```

App-wide base templates and the site-root shell live in the config package:
`src/ucfp/templates/{pages,modals}/`.

## Template Inheritance

### Base Templates

All pages extend an appropriate base template:

```django
{# For main application pages #}
{% extends "pages/base.html" %}

{# For modal dialogs #}
{% extends "modals/base_modal.html" %}
```

### Avoiding Template Logic

**Bad -- logic in the template:**
```django
{% if article.comments.count > 0 and article.is_published and not article.archived %}
  {% for comment in article.comments.all %}
    {% if comment.is_visible %}
      {# display comment #}
    {% endif %}
  {% endfor %}
{% endif %}
```

**Good -- logic in the view:**
```python
context = {
    'visible_comments': article.get_visible_comments(),
    'has_visible_comments': bool( visible_comments ),
}
```
```django
{% if has_visible_comments %}
  {% for comment in visible_comments %}
    {# display comment #}
  {% endfor %}
{% endif %}
```

## Template Tags and Filters

Load required template tags at the top:

```django
{% load static %}
{% load icons %}
```

## Modal Templates

Modal views extend the `ModalView` base (see
[Coding Patterns](../shared/coding-patterns.md)) and a modal base template in
`src/ucfp/templates/modals`.

## Related Documentation
- Frontend guidelines: [Frontend Guidelines](frontend-guidelines.md)
- Icon system: [Icon System](icon-system.md)
- Style guidelines: [Style Guidelines](style-guidelines.md)
- UI testing: [UI Testing](ui-testing.md)
