# Test Data Management

## Visual Testing Page

The development-only visual testing pages live at `http://127.0.0.1:8666/testing/ui/`
(`DEBUG=True`). For the framework, setup, and state-isolation principle, see
[UI Testing](../frontend/ui-testing.md).

## Email Testing

Helper views render and preview email templates with synthetic data:

```
testing/ui/email_test_views.py
```

This requires the email templates to follow the naming patterns the view classes expect.

## Synthetic Data Classes

We never mock DB models; we build real (or in-memory) objects from a centralized
generator so the construction logic is written once and reused. Put these in the
owning module's tests directory -- for an `article` app, in
`article/tests/synthetic_data.py`:

```python
class ArticleSyntheticData:
    @staticmethod
    def create_article( author = None, **kwargs ):
        defaults = {
            'title': 'Test Article',
            'is_published': True,
            'author': author or UserSyntheticData.create_user(),
        }
        defaults.update( kwargs )
        return Article.objects.create( **defaults )
```

For UI test views, build the synthetic object **without** saving it (see
[UI Testing](../frontend/ui-testing.md)); for database/business-logic tests,
`create()` it as above.

## Development Data Injection

`testing.dev_injection.DevInjectionManager` modifies application behavior at
runtime without code changes or a restart -- useful for reaching scenarios that
would otherwise need elaborate backend state:

```python
from testing.dev_injection import DevInjectionManager

manager = DevInjectionManager()
manager.set_injection( 'DEBUG_FORCE_FEATURE_FLAG', { 'enabled': True } )
```

## Test Data Cleanup

Reset shared state in `tearDown` so tests stay isolated:

```python
def tearDown( self ):
    if hasattr( ManagerClass, '_instances' ):
        ManagerClass._instances = {}
    cache.clear()
    super().tearDown()
```

## Related Documentation
- Testing guidelines: [Testing Guidelines](testing-guidelines.md)
- Testing patterns: [Testing Patterns](testing-patterns.md)
- UI testing: [UI Testing](../frontend/ui-testing.md)
