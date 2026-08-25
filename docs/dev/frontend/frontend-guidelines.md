# Frontend Guidelines

## Django Template Guidelines

### Core Principles

1. **Minimal Business Logic**: Keep business logic out of templates. Complex loops, conditionals, and data processing belong in views or custom template tags/filters. No ORM operations in template tags.

2. **View Preparation**: Views should prepare all the data a template needs. Templates primarily display pre-processed data.

3. **Simple Conditionals**: Use only simple `{% if %}` statements for display logic. Avoid complex nested loops or data manipulation.

4. **Custom Template Tags**: Create custom template tags or filters for reusable template logic instead of embedding it directly.

5. **Data Structure**: Structure context data in the view to match the template's needs rather than making the template adapt to raw data.

6. **Load Directives**: All template `load` directives appear at the top of the file, or just below the `extends` directive if there is one.

**Good -- prepare in the view:**
```python
context = {
    'article': article,
    'has_comments': bool( article.comments.exists() ),
    'comment_count': article.comments.count(),
}
```

**Avoid -- business logic in the template:**
```django
{% for comment in article.comments.all %}
  {% if comment.is_visible and not comment.flagged %}
    {# complex nested logic #}
  {% endif %}
{% endfor %}
```

## Template Naming Conventions

- `pages/` - full HTML pages
- `modals/` - HTML modals
- `panes/` - all other HTML page fragments
- `email/` - email templates
- `svg/` - SVG files

For app modules with separate "edit" views, mirror the structure under an `edit/` subdirectory.

## Template Contexts

Once a template context begins to accumulate a large number of entries,
encapsulate them in a dataclass with typed attributes instead of loose strings,
and delegate a helper to build it. Instead of:

```python
return {
    'article': article,
    'comments': comments,
    'comment_form': comment_form,
    'related': related,
    'prev_article': prev_article,
    'next_article': next_article,
}
```

define a dataclass like `ArticleDetailData`, build it in a helper, and return:

```python
article_detail_data = some_helper.build_article_detail_data( article )
return { 'article_detail_data': article_detail_data }
```

## Client-Server Namespace Sharing

We use a **single source of truth** for string constants shared between Python
and JavaScript -- element ids, CSS class names, data-attribute keys -- so the
two sides cannot drift.

- **Source of truth**: `src/ucfp/environment/constants.py` defines the `AppConst`
  class. Each shared value is defined there exactly once.
- **Template access**: `{{ AppConst.NAME }}` (the class is injected by the
  shared-constants context processor).
- **JavaScript access**: `AppConst.NAME` (a JSON copy is injected into
  `window.AppConst` by `pages/base.html`).
- **Derived selectors**: JavaScript is responsible for deriving CSS selector
  forms (prefixing a class name with `.`) as needed.

**Namespace separation**: `AppConst` holds shared constants (data); `App`
(`window.App`) holds the application's JavaScript utilities (behavior).

## JavaScript Standards

**Minimize JavaScript**: Strive for the minimal amount of new JavaScript. Never
do in JavaScript what can be achieved on the backend.

**Server-Side Rendering**: Strive to generate all HTML content server-side.

**Prefer Asynchronous Updates**: The app mimics a single-page application that
avoids full page loads. Prefer dynamic fragment updates (via the `antinode`
framework) over full-page reloads, especially for frequent view changes.

**No JavaScript in Templates**: Never put JavaScript in templates or inline
`<script>` blocks. All JavaScript lives in `src/ucfp/static/js`.

### Core Technologies
- jQuery 3.7 for DOM manipulation
- Bootstrap 4 for UI components
- `antinode` (`common/antinode.py`, `static/js/antinode.js`) for async/ajax updates and modals

**Django Pipeline**: We use Django Pipeline to inject minimized, cache-busting
JavaScript (and CSS). New files must be registered in `src/ucfp/settings/base.py`.

### JavaScript Conventions

1. **Module Pattern**: Use the revealing module pattern for organization.
2. **jQuery Usage**: Prefer jQuery over native DOM manipulation; use a `$` prefix for jQuery objects.
3. **Event Delegation**: Use delegated events for dynamically inserted content.

```javascript
var MyModule = (function() {
    function init() {
        $(document).on('click', '.dynamic-button', handleClick);
    }

    function handleClick(e) {
        e.preventDefault();
        var $button = $(e.currentTarget);
        // handle click
    }

    return { init: init };
})();

$(document).ready(function() {
    MyModule.init();
});
```

## CSS Standards

**No CSS in Templates**: Never put CSS in templates or inline `<style>` blocks.
All CSS lives in `src/ucfp/static/css`.

**Main CSS**: Use `src/ucfp/static/css/main.css` for most needs. A special-purpose,
high-volume CSS module may justify a new file (registered in Django Pipeline).

**No Emojis**: anywhere -- not in user-facing messaging, log messages, or comments.

### CSS Organization

1. **Component-based**: organize CSS by component, not by page.
2. **BEM Naming**: use BEM methodology for class naming where appropriate.
3. **Bootstrap Extensions**: extend Bootstrap classes rather than overriding.
4. **Custom Properties**: use CSS custom properties (the `:root` palette in
   `main.css`) for theming.

```css
.summary-card { /* base */ }
.summary-card__header { /* element */ }
.summary-card--highlighted { /* modifier */ }
```

## View Testing

Views are tested by their response shape. Use `reverse()` (never hardcoded
URLs), test status / response-type / template separately, and use real database
operations and test data. For the full pattern catalog (the five view shapes and
the assertion helpers) see [Testing Patterns](../testing/testing-patterns.md).

```python
def test_article_detail_renders( self ):
    article = Article.objects.create( title = 'Test' )
    response = self.client.get( reverse( 'article_detail', kwargs = { 'pk': article.id } ) )

    self.assertSuccessResponse( response )
    self.assertHtmlResponse( response )
    self.assertTemplateRendered( response, 'article/pages/detail.html' )
    self.assertEqual( response.context['article'], article )
```

## Related Documentation
- Icon system: [Icon System](icon-system.md)
- Style guidelines: [Style Guidelines](style-guidelines.md)
- Template conventions: [Template Conventions](template-conventions.md)
- Interview input UI: [Interview UI Guidelines](interview-ui-guidelines.md)
- JavaScript testing: [JavaScript Testing](javascript-testing.md)
- UI testing: [UI Testing](ui-testing.md)
- Testing patterns: [Testing Patterns](../testing/testing-patterns.md)
