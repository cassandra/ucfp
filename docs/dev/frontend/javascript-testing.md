# JavaScript Testing

This document describes the approach for testing the project's JavaScript modules.

## Overview

JavaScript testing uses the QUnit framework with a local-first approach that
requires no build tools or external dependencies. Tests focus on business-logic
functions rather than DOM manipulation or framework internals.

## Philosophy

- **Local-first**: all dependencies vendored locally, no CDN requirements
- **Lightweight**: QUnit only, no build pipeline
- **Manual execution**: tests run in a browser via simple HTML files
- **Business-logic focus**: test core functions, algorithms, and state management
- **Real browser testing**: an actual browser catches issues that mocks miss

## Framework Choice: QUnit

Selected for:
- Minimal setup (just HTML + script tags)
- No build tools required
- Django-compatible static-file serving
- Comprehensive async testing support
- Small footprint (~25KB minified), vendored under `tests/qunit/`

## Test Structure

```
src/ucfp/static/tests/
├── test-all.html          # Master test runner (recommended)
├── test-{module}.js       # Test cases for each JS module
└── qunit/                 # QUnit framework (vendored)
```

## Running Tests

**Primary workflow (from the project root):**
```bash
make test-js
```
This serves `src/ucfp/static` and opens `http://localhost:8765/tests/test-all.html`
in your browser. Press Ctrl+C to stop the server.

**Directly:**
```bash
open src/ucfp/static/tests/test-all.html
```

## Example Implementation

`main.js` (the `App` namespace) is the worked example:

- **Source**: `src/ucfp/static/js/main.js`
- **Tests**: `src/ucfp/static/tests/test-main.js`

Patterns it demonstrates:
- Time-dependent logic with `Date.now()` / `Math.random()` mocking (`generateUniqueId`)
- `document.cookie` mocking for `setCookie` / `getCookie`
- URL encode/decode round-trips and edge cases

## Testing Best Practices

### Focus Areas (High Value)
- Complex algorithms and timing logic
- State management and transitions
- Feature detection and caching
- Integration between module functions
- Edge cases and boundary conditions

### Avoid Testing (Low Value)
- jQuery DOM-manipulation internals
- Browser event-system mechanics
- Simple property getters/setters
- Framework-provided functionality

### Mocking Strategy
- **Mock system boundaries**: `Date.now()`, `document.cookie`, `window` properties, external APIs
- **Use real objects**: prefer actual module instances over mocks
- **Minimal mocking**: only mock what's necessary for isolation

## Adding New Module Tests

1. **Create the test file** `tests/test-{module}.js` following QUnit patterns:
   ```javascript
   QUnit.module('ModuleName.functionName', function(hooks) {
       QUnit.test('description of test', function(assert) {
           const result = ModuleName.functionName(input);
           assert.equal(result, expected, 'Function returns expected value');
       });
   });
   ```

2. **Update the master runner** `tests/test-all.html`:
   ```html
   <!-- In the source-modules section -->
   <script src="../js/module-name.js"></script>

   <!-- In the test-modules section -->
   <script src="test-{module}.js"></script>
   ```

## Integration with the Development Workflow

- **Manual execution**: part of the JavaScript development process
- **PR checklist**: include "JavaScript tests passing" verification
- **No CI automation**: the lightweight approach prioritizes simplicity
- **Browser compatibility**: test in target browsers (Firefox, Chrome)

This approach balances coverage with simplicity, giving confidence in the
JavaScript without complex tooling overhead. Keep the local-first philosophy for
any future framework additions.
