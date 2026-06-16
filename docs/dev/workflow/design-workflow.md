# Design Workflow

> **Role**: Process Documentation
> **Purpose**: Workflow for design-focused issues -- UX improvements, UI redesigns, mockups, wireframes

## Design Work Documentation Process

When working a design-focused issue (UX, UI redesign, mockups, wireframes,
interaction design), keep the iteration local and share stable versions through
the issue tracker.

### Local Work Directory

All design work products stay local and are **never committed** (`data/` is in
`.gitignore`):

```
data/design/issue-{number}/
├── mockup.html              # Interactive HTML mockups
├── architecture.md          # Technical approach
├── interaction-patterns.md  # UX interaction specifications
└── design-summary.md        # Executive summary
```

### Process

1. **Create the issue subdirectory**: `mkdir -p data/design/issue-{number}`
2. **Iterate locally**: create and refine the design documents.
3. **No repository commits**: design work products stay local only.
4. **Post to the issue**: share stable versions via issue comments/attachments.

## Repository vs Issue Organization

**Repository** (source of truth): implementation code and templates; architecture
docs that affect multiple systems; coding standards and technical guidelines.

**Issue** (design iteration and review): mockups and wireframes; UX interaction
specs; design rationale and trade-offs; review and approval.

## Posting Design Deliverables

Use a consistent structure when posting to the issue:

```markdown
## Phase X Design Complete - Ready for Review

Brief summary of key decisions and deliverables.

### Key Design Decisions
- Decision 1: rationale
- Decision 2: rationale

### Implementation Notes
- Technical considerations
- New development required
```

**Content placement:**
- **Visual deliverables** (interactive HTML mockups, images, diagrams) -> issue
  *attachments* (downloadable, viewable in a browser).
- **Textual content** (architecture, interaction patterns, rationale) -> issue
  *comments* (searchable, linkable, quotable).

## Design Iteration Workflow

1. **Research**: analyze the current implementation and requirements.
2. **Workspace**: set up `data/design/issue-{number}/`.
3. **Iterate**: create and refine mockups and docs locally.
4. **Checkpoint reviews**: post important versions to the issue for feedback.
5. **Final documentation**: post complete deliverables when the design is stable.
6. **Handoff**: provide clear specifications for the implementation phase.

## Multi-Phase Design Strategy

For complex design issues:

**Phase 1 -- Design and Architecture**: complete the design iteration locally,
post comprehensive deliverables, and get approval before implementation.

**Phase 2+ -- Implementation**: use the deliverables as the specification; create
a feature branch and follow the standard
[Workflow Guidelines](workflow-guidelines.md).

### Integration with Development
- **Branches**: a feature branch for any temporary investigation code in the
  design phase; the same or a new feature branch for implementation.
- **Testing**: none required during design; full coverage during implementation.
- **Documentation**: design decisions live in the issue (audit trail);
  implementation detail goes in code and the markdown docs per
  [Documentation Standards](documentation-standards.md).

## Benefits

- **Repository cleanliness**: no work-in-progress artifacts clutter the codebase.
- **Iteration efficiency**: local work allows rapid iteration; failed approaches
  are easy to discard; no merge conflicts during exploration.
- **Review effectiveness**: visual deliverables are easy to access; clear
  approval gates precede implementation.

## Related Documentation
- [Workflow Guidelines](workflow-guidelines.md)
- [Documentation Standards](documentation-standards.md)
- [Frontend Guidelines](../frontend/frontend-guidelines.md)
