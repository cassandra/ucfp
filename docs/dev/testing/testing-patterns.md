# Testing Patterns

## View Testing Architecture

### View Types
Five distinct view patterns, each tested differently:
1. **Synchronous HTML Views** -- traditional Django page views.
2. **Synchronous JSON Views** -- API endpoints.
3. **Asynchronous HTML Views** -- ajax views returning HTML fragments.
4. **Asynchronous JSON Views** -- ajax views returning JSON.
5. **Dual-Mode Views** -- e.g. `ModalView`, handling both sync and async requests.

### Base Test Classes
From `testing.view_test_base`:
- `SyncViewTestCase` -- regular `client.get()` / `client.post()`.
- `AsyncViewTestCase` -- ajax requests via `async_get()` / `async_post()`.
- `DualModeViewTestCase` -- exercises both sync and async modes.

All extend `ViewTestBase` (which itself extends `testing.base_test_case.BaseTestCase`).

### Key Assertion Methods
- **Status**: `assertSuccessResponse()`, `assertErrorResponse()`, `assertServerErrorResponse()`, `assertResponseStatusCode()`
- **Response type**: `assertHtmlResponse()`, `assertJsonResponse()`
- **Templates**: `assertTemplateRendered(response, template_name)`, `assertRedirectsToTemplates(url, templates)`
- **Session**: `assertSessionValue(response, key, value)`, `assertSessionContains(response, key)`
- **Ajax**: `async_get()`, `async_post()`, `async_put()`, `async_delete()`

```python
class ArticleDetailViewTests( SyncViewTestCase ):
    def test_renders( self ):
        article = Article.objects.create( title = 'Test' )
        response = self.client.get( reverse( 'article_detail', kwargs = { 'pk': article.id } ) )
        self.assertSuccessResponse( response )
        self.assertHtmlResponse( response )
        self.assertTemplateRendered( response, 'article/pages/detail.html' )
```

## Manager Async/Sync Testing

Manager classes are singletons that expose dual sync/async methods. Async tests
use a shared event loop to avoid SQLite concurrency issues.

Use `testing.async_task_utils.AsyncTaskTestCase` (a `TransactionTestCase`) for
async manager tests; `AsyncTaskFastTestCase` (a `TestCase`) is the faster variant
when transactional isolation is not required.

- Reset singleton state between tests (e.g. `ManagerClass._instances = {}`).
- Wrap database operations with `sync_to_async()`.

```python
# In an async manager method -- materialize the queryset to prevent lazy loading
articles = await sync_to_async( list )(
    Article.objects.select_related( 'author' ).all()
)

# In a test -- wrap the ORM call
article = await sync_to_async( Article.objects.create )( title = 'Test' )
```

## Django-Specific Patterns

### Abstract Model Testing
Define a concrete subclass of the abstract model inside the test module and test
that, rather than the abstract base directly.

### Singleton Manager Testing
Verify the singleton identity: `self.assertIs( manager_a, manager_b )`, and reset
`_instances` in `tearDown`.

### Authentication Testing
- Protected views should redirect unauthenticated requests to login.
- Use `self.client.force_login( user )` for authenticated cases.

### Form Validation Testing
- Success: assert the redirect and the resulting database change.
- Errors: a form error returns status 200; assert with `assertFormError()`.

### File Upload Testing
Isolate filesystem writes by pointing `MEDIA_ROOT` at a temporary directory for
the duration of the test (set in `setUp`, clean up in `tearDown`), so uploads
never touch the real media tree.

## Related Documentation
- [Testing Guidelines](testing-guidelines.md)
- [Test Data Management](test-data-management.md)
- [UI Testing](../frontend/ui-testing.md)
- [Backend Guidelines](../backend/backend-guidelines.md)
