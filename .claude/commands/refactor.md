---
allowed-tools: Bash, Read, TodoWrite, Grep, Glob, Task
description: Plan and execute refactoring with expert analysis
argument-hint: [target] (e.g., ClassName, module_name, or file_path)
---

Plan refactoring for: "$0"

## Expert Refactoring Planning Process

1. **Use TodoWrite to plan refactoring phases** - Track analysis and implementation
   - Read `docs/CLAUDE.md` for development philosophy and well-factored-code principles
   - Use specialized agents for expert refactoring analysis

2. **Analyze the current implementation**:
   - Search for the target "$0" across the codebase
   - Identify all usages and dependencies
   - Understand current patterns and structure
   - Document existing behavior and interfaces

3. **Use specialized refactoring agents** - Get expert analysis (launch in parallel where applicable):
   - **backend-dev** agent: Django patterns, database design, architecture
   - **test-engineer** agent: test-impact assessment and strategy
   - **general-purpose** agent: broad dependency and cross-domain analysis
   - **code-quality** agent: standards compliance and maintainability assessment

4. **Identify refactoring opportunities**:
   - Code duplication and consolidation
   - Single-Responsibility violations
   - Coupling and cohesion issues
   - Performance bottlenecks
   - Maintainability concerns and testing gaps

5. **Assess impact and risk**:
   - Files and components affected
   - Breaking-change potential
   - Test coverage requirements
   - Performance implications
   - Rollback considerations

6. **Plan refactoring phases** - following the multi-phase strategy in `docs/dev/workflow/workflow-guidelines.md`:
   - **Phase 1**: core structural improvements (no behavior changes)
   - **Phase 2**: interface improvements and optimizations
   - **Phase 3**: advanced features and enhancements
   - Each phase independently valuable.

7. **Create an implementation strategy** - step-by-step sequence, safe transformation techniques, a test-driven approach, validation checkpoints, and rollback strategies.

8. **Generate the deliverables** - current-state analysis and pain points, target structure, the phase-by-phase plan, risk assessment and mitigation, the per-phase testing strategy, and success criteria.

**Refactoring guidelines:**
- Maintain existing behavior (no functional changes in Phase 1).
- Ensure comprehensive test coverage.
- Use incremental, safe transformations.
- Plan for rollback at each phase.

**Refactoring target:** "$0"
**Goal:** well-factored code following our architecture principles -- thoughtful responsibility boundaries, proper encapsulation, readability and maintainability (see `docs/CLAUDE.md`).

Begin refactoring analysis now.
