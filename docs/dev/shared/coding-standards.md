# Coding Standards

## Code Conventions Checklist

Checklists for writing and reviewing code.

**General**:
- [ ] Code does not use hard-coded "magic" strings.
- [ ] Code does not use any hard-coded "magic" numbers.
- [ ] All comments add value and follow our commenting guidelines.
- [ ] No urls appear as hard-coded paths; all use Django url names and `reverse()`.
- [ ] There are no `.flake8` linting violations.
- [ ] The file ends with a newline.
- [ ] All new files follow the project structure's name and location conventions.
- [ ] There are no emojis in any code, templates, or documentation.
- [ ] All comments and docstrings use ASCII only (no em/en dashes, smart quotes, arrows, degree symbols, ellipses, etc.).

**Imports**:
- [ ] All module imports are at the top of the file.
- [ ] Imports are grouped logically: system/pip, django, project, then module-local.
- [ ] Imports have one blank line between groups.
- [ ] Within a group, imports are sorted alphabetically.
- [ ] No module relies on indirect (hidden) imports.
- [ ] There are no unused imports.

**Method Declarations**:
- [ ] All methods use type hints for their parameters and return values.
- [ ] All method definitions with more than two arguments use one line per argument.
- [ ] All multi-line method signatures have their types and default values aligned.
- [ ] No methods return position-dependent tuples.

**Class Declarations**:
- [ ] All dataclass definitions have their types and default values aligned.
- [ ] All enum definitions have their types and values aligned.
- [ ] Enums subclass `LabeledEnum`.

**Method Calling**:
- [ ] All method calls use named parameters.
- [ ] All method calls with more than two arguments use one line per argument.
- [ ] All multi-line method calls use a comma after the last item.
- [ ] Spaces surround all equals (`=`) signs when passing parameters to methods.

**Expressions**:
- [ ] All boolean assignments to conditional clauses are wrapped in `bool()`.
- [ ] All loops end with an explicit `continue` or a `return`.
- [ ] All methods end with an explicit `return` or a `raise`.
- [ ] Compound/complex conditional statements use explicit delimiting parentheses.
- [ ] Single quotes are used for all strings in Python code.
- [ ] All multi-line arrays, dictionaries, and sets use a comma after the last item.

**Views**:
- [ ] All url path components follow our standard ordering conventions.
- [ ] All Django url names follow our standard naming conventions.
- [ ] All view names match their url names (except for casing and underlining).
- [ ] All views raise exceptions for common error conditions (let middleware handle it).

**Templates**:
- [ ] Template names referenced in views closely match the view names that use them.
- [ ] No templates have in-line Javascript.
- [ ] No templates have in-line CSS.
- [ ] Templates appear in a subdirectory matching their purpose: modals, panes, pages.
- [ ] Template tag `load` statements are near the top of the file.
- [ ] Django template comments use `{# #}` (single line) or `{% comment %}...{% endcomment %}` (multi-line), never `<!-- -->` (HTML comments ship to the browser).

## Code Conventions Details

### No "magic" strings

We do not use "magic" or hard-coded strings when needing multiple references.
Any string used in two or more places risks the copies being mismatched. This
includes, but is not limited to:

- All DOM ids and class strings shared between client and server must adhere to
  our `AppConst` pattern. See "Client-Server Namespace Sharing" in
  [Frontend Guidelines](../frontend/frontend-guidelines.md).
- Any string used multiple times but only in client/Javascript should be a
  constant defined inside the module, or in `main.js` if shared across modules.

### Type Hints

- We add type hints to dataclass fields, method parameters, and method return values.
- We do not add type hints to locally declared method variables.
- Some allowed, but not required, exceptions:
  - The `request` parameter when appearing in a Django view class.
  - Single-parameter methods where the method or parameter name makes its type unambiguous.

### Method Parameter Formatting

Besides adding type hints, we adhere to the following for readability:
- For methods with a single parameter, or parameters of native types, they can
  appear on one line with the method name.
- With more than one parameter and app-defined types, use a multi-line declaration.
- For three or more parameters, use one line per parameter and align the type names.

**Good Examples**:

```
    def set_name( self, name : str ) -> Record:

    def set_rank( self, record_id : int, rank : int ) -> Record:

    def set_position( self,
                      record_id : int,
                      label     : str,
                      offset    : int  ) -> Record:
```

**Bad Examples**:

```
    def set_record_type( self, record_id : int, record_type : RecordType ) -> Record:

    def set_position( self,
                      record_id : int,
                      label : str,
                      offset: int ) -> Record:

    def set_position( self, record_id : int,
                      label : str, offset: int ) -> Record:
```

### Variable Assignment vs Inlining

We prefer explicit variable assignment over inlining function calls. This is not
about minimizing lines of code -- it is about readability and debuggability.

**Good** -- Named intermediate values
```python
table_name = self.queryset.model._meta.db_table
logger.debug( f"Processing table: {table_name}" )

cutoff_date = datetimeproxy.now() - timedelta( days = 30 )
old_records = queryset.filter( created__lt = cutoff_date )
```

**Bad** -- Inlined function calls
```python
logger.debug( f"Processing table: {self.queryset.model._meta.db_table}" )

old_records = queryset.filter(
    created__lt = datetimeproxy.now() - timedelta( days = 30 )
)
```

Benefits of variable assignment:
- Provides semantic naming that clarifies intent.
- Easier to debug (you can inspect intermediate values).
- Improves readability by breaking up complex expressions.
- Allows reuse without recalculation.

### Explicit Booleans

When assigning or returning a boolean, wrap the expression in `bool()` to make
the intended type explicit:

**Good**
```python
   is_active = bool( user.last_login )
   in_modal_context = bool( request.POST.get('context') == 'modal' )
```

**Bad**
```python
   is_active = user.last_login
   in_modal_context = request.POST.get('context') == 'modal'
```

### Complex Boolean Expressions

- For conditionals with multiple clauses, explicitly enclose each clause in
  parentheses to make the intent clear.
- Do not rely on the reader's deep understanding of operator precedence.
- Use one line per clause unless the combined clauses are very short and obvious.
- A single boolean-typed variable or a method that returns a boolean does not
  need parentheses.

**Good**:
```
    if is_editing and selected_item:
        pass

    if (( request.method == 'POST' )
          and ( 'confirm' in request.POST )):
        pass

    if ( status in active_status_set
         and tag_set.intersection( PRIORITY_TAG_SET )):
        pass
```

**Bad**:
```
    if request.method == 'POST' and user_role == 'admin':
        pass
```

### Control Flow Statements

- Always include an explicit `continue` statement in loops.
- Always include an explicit `return` statement in functions.
- This improves readability and makes control-flow intent explicit.

```python
def process_items( items ):
    results = []
    for item in items:
        if not item.valid:
            continue  # Explicit continue for invalid items

        if item.needs_processing:
            results.append( process( item ) )
            continue  # Explicit continue after processing

        results.append( item.default_value )
        continue  # Explicit continue at end of loop

    return results  # Explicit return at end of function
```

### Operator Spacing

- Use spaces around assignment and most other operators in expressions, e.g.
  `x = y + z`, `result += value`, `if count == 0`.
- We *do* keep spaces around keyword-argument equals (`func( x = y )`) -- a
  deliberate deviation; see the flake8 note below.

### Parentheses Spacing (Deliberate PEP8 Deviation)

- **We prefer spaces inside parentheses for enhanced readability.**
- This is a deliberate deviation from PEP8 (E201, E202).
- Examples:
  - Good: `if ( condition ):`
  - Good: `my_function( param1, param2 )`
  - Good: `result = calculate( x + y )`
- This applies to all parentheses: function calls, conditionals, expressions.
- Rationale: extra spacing visually separates content from its delimiters.

### Linting: Flake8 Configurations

The project uses two flake8 configurations (run from `src/`):

- **Development** (`src/.flake8`): our preferred style for daily work, with
  whitespace deviations from PEP8 for readability:
  - **E201, E202**: spaces inside parentheses.
  - **E221**: aligned operators and values in multi-line declarations.
  - **E251**: spaces around keyword parameters.
  - These are deliberate choices, not oversights. `make lint-strict` enforces them.
- **CI** (`src/.flake8-ci`): the lenient, real-errors-only config that GitHub
  Actions enforces (`make lint`); it blocks merging on violations.

### ASCII-Only in Comments and Docstrings

Comments and docstrings use ASCII only. The benefits of visually-precise Unicode
characters (em dashes, arrows, degree symbols) are outweighed by the costs:
inconsistent rendering across terminals / diff viewers / editor configs; broken
`grep` for anyone typing the ASCII equivalent; copy-paste mismatches between
source and rendered docs; and visual ambiguity between similar-looking characters.

Common substitutions:

| Unicode | ASCII |
|---------|-------|
| em dash, en dash | `--` or `-` |
| right arrow, left-right arrow | `->` or `and` |
| horizontal ellipsis | `...` |
| multiplication sign | `x` |
| degree symbol | drop or restructure (e.g., `88F` instead of `88 deg F`) |
| smart quotes, smart apostrophes | `"` `'` |

This is a syntactic concern (like the no-emoji rule) and is enforced during the
comment-cleanup pass.

Scope: applies to comments and docstrings. It does **not** apply to user-facing
strings (`help_text`, `verbose_name`, error messages, log messages) -- those
follow their own UI / operator-copy conventions and may contain whatever
characters their audience needs.

## Commenting

The content and semantics of comments -- what to keep, rewrite, or remove -- are
covered in [Commenting Guidelines](commenting-guidelines.md). The checklist above
covers the syntactic surface only.

### Special Cases

#### TRACE Pattern (Accepted)
- `TRACE = False  # for debugging` is an accepted pattern.
- It works around a Python logging limitation (no TRACE level below DEBUG).

## Related Documentation
- Commenting content and semantics: [Commenting Guidelines](commenting-guidelines.md)
- Testing standards: [Testing Guidelines](../testing/testing-guidelines.md)
- Backend patterns: [Backend Guidelines](../backend/backend-guidelines.md)
- Frontend standards: [Frontend Guidelines](../frontend/frontend-guidelines.md)
- Workflow and commits: [Workflow Guidelines](../workflow/workflow-guidelines.md)
