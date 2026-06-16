# Django Testing Anti-Patterns and Lessons Learned

Lessons from converting heavily-mocked Django tests to real-object tests. The
examples use generic models (`Article`, `Comment`, `Tag`) to illustrate the
pattern. See [Testing Guidelines](testing-guidelines.md) for the rules these
lessons reinforce.

## Core Anti-Patterns

### 1. Over-mocking database operations

**Problem**: mocking basic model creation, relationships, and queries instead of
using real objects in the test transaction.

```python
# Anti-pattern: mocking basic model operations
@patch.object( ArticleManager, 'publish' )
def test_publish( self, mock_publish ):
    mock_publish.return_value = True   # proves nothing about the DB
```

```python
# Better: assert real database state
def test_publish( self ):
    self.assertFalse( Article.objects.get( pk = self.article.pk ).is_published )
    self.client.post( reverse( 'article_publish', kwargs = { 'pk': self.article.pk } ) )
    self.assertTrue( Article.objects.get( pk = self.article.pk ).is_published )
```

**Lesson**: Django's test framework gives you isolated database transactions.
Use real objects rather than mocking CRUD.

### 2. Mocking view delegation instead of testing integration

**Problem**: mocking an entire delegated view class hides real integration issues.

```python
# Anti-pattern: mocking the delegated view
@patch( 'article.views.CommentReorderView' )
def test_reorder_comments( self, mock_view_class ):
    mock_view_class.return_value.post.return_value = JsonResponse( { 'status': 'ok' } )
```

```python
# Better: test the full path and verify the resulting order
def test_reorder_comments( self ):
    response = self.client.post( url, post_data )
    ordered = list( self.article.comments.order_by( 'order_id' ) )
    self.assertEqual( ordered[0], comment_three )
```

**Lesson**: test the full integration path, not the delegation mechanics.

### 3. Wrong response-type expectations

**Problem**: expecting a 302 redirect when the view actually returns JSON via the
`antinode` ajax integration.

```python
# Anti-pattern
response = self.client.post( url, { 'action': 'confirm' } )
self.assertEqual( response.status_code, 302 )   # wrong for an antinode view
```

```python
# Better: expect JSON from antinode views
response = self.client.post( url, { 'action': 'confirm' } )
self.assertSuccessResponse( response )
self.assertJsonResponse( response )
self.assertEqual( response.json()['location'], expected_url )
```

**Lesson**: know your app's ajax/async response patterns. With `antinode`, many
views return JSON instead of a redirect.

## Model Relationship Discoveries

### Many-to-many through models

A many-to-many often goes through an explicit "through" model, not a direct
relationship:

```python
# Wrong - no direct relationship
self.article.tags.add( self.tag )

# Right - use the through model
ArticleTag.objects.create( article = self.article, tag = self.tag )
```

**Lesson**: verify the model relationship (in the model definition or admin)
before writing the test. Complex logic frequently involves intermediate models
that are not obvious from the call site.

## Form Validation Requirements

A form may require fields beyond the obvious ones; partial POST data silently
fails to change the database.

```python
# Incomplete - the update silently does not happen
self.client.post( url, { 'title': 'New' } )   # missing required 'slug', 'body'
```

**Lesson**: check the form's required fields, and read the form's validation
errors to debug a database change that did not occur.

## Session and Middleware Requirements

Many views depend on session state set up by custom middleware. Establish that
state in `setUp`:

```python
def setUp( self ):
    super().setUp()
    # set whatever session/context state the view's decorators/middleware require
    ...
```

**Lesson**: understand your middleware dependencies; a view may need specific
session state to function at all.

## Test Infrastructure Patterns

### Synthetic data
The project uses a consistent synthetic-data pattern per module
(`<app>/tests/synthetic_data.py`) so construction logic is written once:

```python
class ArticleSyntheticData:
    @staticmethod
    def create_article( **kwargs ):
        defaults = { 'title': 'Test Article', 'is_published': True }
        defaults.update( kwargs )
        return Article.objects.create( **defaults )
```

### Test base classes
Use the application's base classes (`testing.view_test_base`) rather than
recreating them: `SyncViewTestCase`, `AsyncViewTestCase`, `DualModeViewTestCase`,
and the custom assertions (`assertSuccessResponse()`, `assertJsonResponse()`,
`assertHtmlResponse()`, `assertTemplateRendered()`). See
[Testing Patterns](testing-patterns.md).

## Enum and ID Conventions

### LabeledEnum string conversion
Enum-backed model fields store the enum's string form -- convert with `str()`:

```python
article = Article.objects.create( status_str = str( ArticleStatus.PUBLISHED ) )
```

### Shared HTML id formats
Element ids shared between server and client come from the `AppConst` single
source of truth (see [Frontend Guidelines](../frontend/frontend-guidelines.md)),
not hard-coded strings -- so tests that assert on an id should derive it the same
way the template does, not duplicate the literal.

## Error Handling

Views raise custom exceptions that middleware converts to the right HTTP status
(e.g. a not-allowed error becomes a 405) rather than returning the status
directly. Test the outcome (the status / response), and let the middleware do its
job.

## Best Practices Derived

1. **Test real behavior, not implementation details** -- database state changes
   and full request/response cycles, not method calls or delegation mechanics.
2. **Understand the architecture** -- middleware dependencies, session patterns,
   enum/string conversions, model relationships.
3. **Use the app's test utilities** -- base classes, synthetic-data generators,
   custom assertions.
4. **Debug systematically** -- read the error (it often reveals missing setup);
   check form requirements when a DB change does not happen; verify the response
   type matches expectations (JSON vs HTML vs redirect).

## Conclusion

Moving from over-mocked tests to real-object tests reveals real architecture and
yields tests that actually catch regressions. Django's test framework is built to
run real database operations in isolated transactions -- mocking basic CRUD is
unnecessary and counterproductive, and produces fragile tests that give false
confidence.
