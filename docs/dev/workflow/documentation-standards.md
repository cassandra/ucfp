# Documentation Standards

> **Role**: Process Documentation
> **Purpose**: How in-repository documentation is organized, written, and maintained

## Documentation Philosophy

Documentation comes in two flavors: **work-in-progress** and **source of truth**.
Work-in-progress docs live *outside* the repository -- in issues, commit messages,
and PR descriptions.

In-repository documentation is either markdown (the `docs` directory) or in-code
(comments and docstrings, everywhere else).

- **No redundancy**: a markdown doc should not repeat what the code says. Refer to
  the code for details; use markdown for higher-level explanation.
- **Appropriate location**: single-module implementation detail belongs in that
  module's comments. Markdown is for higher-level concepts and inter-module
  interaction patterns.

### Role-Based Organization

Developer docs (`docs/dev/`) are organized by role:
- **shared**: common reference used across roles (project structure, coding
  standards/patterns, commenting, environment variables).
- **backend**: models, views, business logic, architecture.
- **frontend**: templates, styling, JavaScript, UI patterns.
- **testing**: testing guidelines, patterns, and data management.
- **workflow**: process docs -- workflow, design, releases, rollback.

### Document Structure

Each role-specific document follows this shape:

```markdown
# Document Title

> **Role**: [role]
> **Purpose**: [brief description]

## Main Content Sections

## Related Documentation
- Link to related docs in other roles
```

## Cross-Reference Management

Use relative paths for cross-role references:

```markdown
## Related Documentation
- Testing patterns: [Testing Patterns](../testing/testing-patterns.md)
- Backend: [Backend Guidelines](../backend/backend-guidelines.md)
```

When updating docs: check for broken cross-references, update links when moving
or renaming files, and keep linking bidirectional where it helps.

## Writing Standards

- Write for the target role; assume role-appropriate knowledge.
- Prefer concrete examples over abstract description; use code to illustrate.
- **Bold** for important concepts; `code formatting` for filenames, commands, and
  code elements; `>` blockquotes for the role/purpose header; bullets for lists,
  numbered lists for procedures.
- Keep example code complete enough to be useful:

```python
class ArticleManager( models.Manager ):
    def published( self ):
        return self.filter( is_published = True )
```

## Content Organization

- Keep each document focused on its role; split large docs into logical subsections.
- Keep common standards in `shared/` and reference them rather than duplicating,
  to maintain a single source of truth.
- Information hierarchy: primary (essential to the role), secondary (helpful
  context), reference (links elsewhere).

## Maintenance

- Review periodically for accuracy; update examples when code patterns change;
  verify cross-references stay valid.
- All documentation changes go through the PR process; ship doc updates *with* the
  related code change. Treat documentation as first-class code.
- Deprecation: mark deprecated patterns with a clear warning, provide a migration
  path, and remove after a transition period.

## Agent-Friendly Guidelines

- Each role's docs should be self-contained enough to orient an AI agent without
  overwhelming it; cross-references supply the rest.
- Use consistent terminology and clear section headers for searchability.

## Related Documentation
- Workflow guidelines: [Workflow Guidelines](workflow-guidelines.md)
- All role-specific docs serve as examples of these standards.
