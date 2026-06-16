# UI Testing

A visual testing framework for viewing UI styling and layout during development.
These are **read-only** views that render templates with synthetic data; they
must never modify real system state.

## Visual Testing Page

Visit `http://127.0.0.1:8666/testing/ui/` (dev server). The testing URLs are
served by the `testing` app and are only mounted when `DEBUG=True` (gated in the
root `ucfp/urls.py`). A worked example app lives at `src/user/tests/ui`.

## Critical Principle: System State Isolation

**Never modify real system state in a UI test view:**
- Do not add data to real managers or singletons.
- Do not write to the database or modify caches.
- Do not persist anything that could appear in production views.

Build **synthetic** objects in memory and render templates directly with them.

## How Auto-Discovery Works

`testing/discovery.py` scans each app for a `tests/ui/` package and mounts its
`urls.py` under `/testing/ui/`. To add a visual testing page to an app:

```bash
mkdir -p <app>/tests/ui
touch <app>/tests/__init__.py <app>/tests/ui/__init__.py
```

Then create:
- `<app>/tests/ui/views.py`
- `<app>/tests/ui/urls.py` (auto-discovered)
- templates under `<app>/templates/<app>/tests/ui/`

## View Implementation

Render a template directly with synthetic (unsaved) objects:

```python
# <app>/tests/ui/views.py
from django.shortcuts import render
from django.views import View

from article.models import Article

class TestUiArticleCardView( View ):
    def get( self, request, *args, **kwargs ):
        articles = [
            self._synthetic_article( 'Published example', is_published = True ),
            self._synthetic_article( 'Draft example', is_published = False ),
        ]
        context = { 'articles': articles, 'page_title': 'Article Card Variations' }
        return render( request, 'article/tests/ui/card_variations.html', context )

    def _synthetic_article( self, title, is_published ):
        # In-memory only -- never .save()
        return Article( title = title, is_published = is_published )
```

```python
# <app>/tests/ui/urls.py
from django.urls import re_path

from . import views

urlpatterns = [
    re_path( r'^$', views.TestUiArticleHomeView.as_view(), name = 'article_tests_ui' ),
    re_path( r'^cards/$', views.TestUiArticleCardView.as_view(), name = 'test_article_cards' ),
]
```

## Template Structure

A test home page extends the standard base and links the component pages:

```django
{% extends "pages/base.html" %}
{% load icons %}

{% block content %}
<div class="container-fluid m-4">
  <h2>{{ app_name|title }} UI Tests</h2>
  <ul class="list-group">
    <li class="list-group-item">
      <a href="{% url 'test_article_cards' %}">Article Cards</a>
    </li>
  </ul>
</div>
{% endblock %}
```

## Component Testing Patterns

Use the visual pages to exercise the cases that are hard to reach in production:

- **State variations** -- render one component across every state it can take
  (published/draft, empty/full, error/normal) on a single page.
- **Responsive layout** -- view the component at tablet/desktop widths (the
  primary targets; see [Style Guidelines](style-guidelines.md)).
- **Icon usage** -- confirm icons render at the intended sizes/colors (see
  [Icon System](icon-system.md)).
- **Modals and forms** -- render modal sizes and form states (normal, invalid,
  disabled) directly, without driving the real workflow.

Keep shared construction logic in a centralized synthetic-data helper rather than
duplicating it across test views -- see
[Test Data Management](../testing/test-data-management.md).

## Related Documentation
- Frontend guidelines: [Frontend Guidelines](frontend-guidelines.md)
- Template conventions: [Template Conventions](template-conventions.md)
- Testing patterns: [Testing Patterns](../testing/testing-patterns.md)
- Test data management: [Test Data Management](../testing/test-data-management.md)
