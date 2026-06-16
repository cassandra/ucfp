# Testing Guidelines

## Running Tests

Run all the tests with:

```bash
make test
```

Run a subset using the Django test path:

```bash
make test ARGS=<ucfp.test.module.path>
```

Tests run under `IsolatedTestRunner` (`testing/runner.py`), which swaps the Redis
client for `fakeredis` and uses Django's cache backend -- so tests need no real
Redis and leave no shared state behind.

## Overall Guidelines

**Do not mock unless absolutely necessary.** Use real system components and build
test data (the `synthetic_data.py` pattern). Tests exist to catch when internal
components stop integrating correctly; mocking internal app boundaries masks
exactly those failures. We rarely want "pure" unit tests.

**Mock only at external system boundaries** -- things outside the codebase, or
that would leave artifacts (third-party API calls, filesystem writes under
`MEDIA_ROOT`).

**Never write a test that depends on log messages, human-readable strings, or
other hard-coded strings.** Test outcomes, not implementation details.

## High-Value vs Low-Value Testing

### HIGH-VALUE Tests (Focus Here)
- Database constraints and cascade-deletion behavior -- data integrity.
- Complex business logic and algorithms -- calculations, aggregation, processing.
- Singleton/manager behavior -- initialization, thread safety.
- Enum conversions with custom logic (e.g. `from_name_safe()`, business rules).
- File handling and storage -- upload, deletion, cleanup, error handling.
- External-system interface parsing -- API boundaries.
- Caching and performance optimizations -- TTL caches, indexing.
- Auto-discovery and Django startup integration.
- Thread safety and concurrent operations -- locks, shared state, races.
- Background-process coordination -- async/sync dual access, event loops.

### LOW-VALUE Tests (Avoid)
- Simple getters/setters that just return a field.
- Django ORM internals (Django already tests these).
- Trivial enum label checks without business logic.
- Basic field access and obvious defaults.
- Simple string formatting without complex logic.

## Critical Testing Anti-Patterns

### Never test behavior based on log messages

Log assertions break whenever logging changes, and many tests disable logging.
Test the actual behavior change instead -- state, return values, side effects.

```python
# BAD - asserting on log output
with self.assertLogs( 'orders.manager', level = 'WARNING' ) as log_context:
    manager.process_data( invalid_data )
    self.assertTrue( any( "Error processing" in m for m in log_context.output ) )

# GOOD - asserting on behavior
with patch.object( manager, 'fallback_handler', mock_fallback ):
    result = manager.process_data( invalid_data )
    mock_fallback.assert_called_once()
    self.assertIsNone( result )
```

### Never mock a class when the real class is available

Tests that verify mock calls instead of behavior prove nothing about what the
code actually does:

```python
# BAD - testing the mock, not the behavior
def test_process_data( self, mock_service ):
    mock_service.return_value = { 'status': 'success' }
    processor.process_data( input_data )
    mock_service.assert_called_once_with( expected_params )  # but what did it return?

# GOOD - testing the return value and state
def test_process_data_returns_transformed_result( self, mock_service ):
    mock_service.return_value = { 'status': 'success', 'data': 'raw_value' }
    result = processor.process_data( input_data )
    self.assertEqual( result['transformed_data'], 'processed_raw_value' )
    self.assertEqual( result['status'], 'completed' )
```

### Do not over-mock internal components

Mock only at the system boundary; let real data flow through real internal code:

```python
# BAD - mocking the HTTP layer AND the internal converter (tests nothing)
@patch( 'module.http_client.get' )
@patch( 'module.DataConverter.parse' )
def test_fetch_and_parse( self, mock_parse, mock_get ):
    ...

# GOOD - mock only the boundary
@patch( 'module.http_client.get' )
def test_fetch_and_parse_integration( self, mock_get ):
    mock_get.return_value = Mock( text = '{"real": "json"}' )
    result = service.fetch_and_parse()
    self.assertIsInstance( result, ExpectedDataType )
```

## Best Practices Summary

1. Mock at system boundaries only (HTTP, external services).
2. Test return values and state changes, not mock-call parameters.
3. Use real data through real code paths when possible.
4. Focus on interface contracts, not implementation details.
5. Create focused tests -- one behavior each.
6. Test meaningful edge cases that affect business logic.
7. Verify data transformations end-to-end.
8. Prefer real database operations over ORM mocking; `TransactionTestCase`
   gives proper isolation for database-dependent tests.

## Django-Specific Patterns

See [Testing Patterns](testing-patterns.md) for abstract-model testing, singleton
manager testing, async/sync manager testing, authentication, forms, and file
uploads.

## Development Data Injection

The development data-injection system (`testing.dev_injection.DevInjectionManager`)
lets you change application behavior at runtime, without code edits or a restart,
to reach test scenarios that would otherwise need elaborate backend setup. See
[Test Data Management](test-data-management.md).

## Related Documentation
- Django-specific patterns: [Testing Patterns](testing-patterns.md)
- Test data management: [Test Data Management](test-data-management.md)
- JavaScript testing: [JavaScript Testing](../frontend/javascript-testing.md)
- Coding standards: [Coding Standards](../shared/coding-standards.md)
- View testing overview: [Frontend Guidelines](../frontend/frontend-guidelines.md#view-testing)
