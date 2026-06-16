# Backend Guidelines

## Core Concepts and Modules

### App Module Structure
See [Project Structure](../shared/project-structure.md).

### Key Base Classes
- `common.singleton.Singleton` -- base for singletons; `SingletonSync` is the
  synchronous variant.
- `common.singleton_manager.SingletonManager` -- base for manager classes
  (a `Singleton` with sync/async initialization).
- `common.labeled_enum.LabeledEnum` -- base for all enums.
- `common.labeled_enum.LabeledEnumField` -- model field for storing a
  `LabeledEnum` (use this rather than Django `choices`); `NullableLabeledEnumField`
  for nullable columns.

## Design Patterns

### Singleton Manager Pattern
Core, app-wide functionality uses a singleton manager with thread-safe init:
- Implement `__init_singleton__()`, not `__init__()`.
- Access via `cls.instance()`.
- Provide `ensure_initialized()` and `ensure_initialized_async()`.

### Dual Sync/Async Support
A manager that is reached from both Django views (sync) and background tasks
(async) exposes both forms of its methods -- e.g. `get_data()` /
`get_data_async()`. ORM access inside async methods goes through
`asgiref.sync.sync_to_async`. See [Testing Patterns](../testing/testing-patterns.md)
for how these are tested (`testing.async_task_utils.AsyncTaskTestCase`).

### Database Patterns
- **Strategic indexing**: `db_index=True` and composite indexes, only where a
  real query needs them.
- **Foreign keys**: use `select_related()` (and `prefetch_related()` for
  many-relations) to avoid N+1 queries.
- **Enum storage**: a `CharField`-backed `LabeledEnumField`, not Django `choices`.

## Django View Philosophy

### Keep Views Lightweight
Delegate complex logic out of the view:
- **Template data** -> encapsulate a large context in a typed object
  (`schemas.py`).
- **Business logic** -> service/helper classes (`services.py` / `*_helpers.py`).
- **Database queries** -> manager classes.
- **Structure construction** -> dedicated builder classes.

### View Patterns
- Use mixins for cross-view functionality.
- Use the existing base classes for specialized behavior (e.g. `ModalView` for
  modal dialogs).
- Always use Django URL names and `reverse()`, never hardcoded URLs.

## Performance Patterns

### Caching
- TTL caching via `cachetools.TTLCache` guarded by a thread lock.
- `collections.deque` (bounded) for circular/rolling buffers.

### Threading and AsyncIO
- Background work runs on daemon threads with graceful shutdown (see the
  `background` app and `background/startup.py`).
- For ORM access from async code, use `asgiref.sync.sync_to_async`.

## Development Tools

### Debug Settings
Toggle these in `src/ucfp/settings/development.py`:
- `SUPPRESS_SELECT_REQUEST_ENDPOINTS_LOGGING` -- hide high-frequency polling requests from the log.
- `SUPPRESS_MONITORS` -- disable background monitor tasks during development.
- `BASE_URL_FOR_EMAIL_LINKS` -- the base URL used when rendering email links locally.

## Related Documentation
- [Coding Patterns](../shared/coding-patterns.md)
- [Project Structure](../shared/project-structure.md)
- [Testing Guidelines](../testing/testing-guidelines.md)
