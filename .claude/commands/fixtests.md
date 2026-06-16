---
allowed-tools: Bash, Read, TodoWrite, Grep, Glob, Task
description: Systematic test failure analysis and remediation
argument-hint:
---

Systematic test failure analysis and remediation:

## Test Remediation Process

Focus on fixing failing tests to achieve a fully passing suite:

1. **Use TodoWrite to plan the remediation workflow** - Track systematic fixing

2. **Review project documentation** - Understand standards and guidelines:
   - `docs/CLAUDE.md` for AI escalation patterns and quality standards
   - `docs/dev/shared/coding-standards.md` for coding standards
   - `docs/dev/testing/testing-guidelines.md` for testing best practices
   - `docs/dev/testing/testing-lessons-learned.md` for complex cases

3. **Run the full test suite** - Identify all current failures:
   ```bash
   make test
   ```
   Capture the complete output to understand the scope and nature of the failures.

4. **Categorize the failures** - By type and complexity:
   - **Syntax/import errors** - basic issues preventing test execution
   - **Logic failures** - incorrect assertions or logic
   - **Configuration issues** - environment, settings, or dependency problems
   - **Integration failures** - database or component integration issues
   - **Flaky tests** - intermittent failures from timing or state
   - **Outdated tests** - tests that no longer match the implementation

5. **Assess test value** - high / medium / low / questionable, per the testing guidelines.

6. **Create a prioritized remediation plan**:
   - **P1** - syntax/import errors (blocking other tests)
   - **P2** - high-value logic and integration failures
   - **P3** - medium-value failures
   - **P4** - configuration and environment issues
   - **P5** - flaky-test stabilization
   - **P6** - low-value test assessment (fix, rewrite, or discuss removal)

7. **Use specialized test analysis** - Get expert assistance:
   - **test-engineer** agent: test analysis and fixing strategies (the no-internal-mocking policy)
   - **backend-dev** agent: Django test patterns and database issues
   - **code-quality** agent: standards compliance of the fixed tests

8. **Execute systematic fixing** - Follow the prioritized plan:
   - Work through each priority level systematically.
   - Fix tests per the testing guidelines (no internal mocking; real DB + synthetic data).
   - **Apply the 3-attempt rule** - if struggling with a test after 3 attempts, pause and escalate.
   - Run tests frequently to verify fixes don't break others.

9. **Reference resources for hard cases** - search `docs/dev/testing/testing-lessons-learned.md` and `docs/dev/testing/testing-patterns.md` for related guidance.

10. **Validate test quality** - no compromising coverage or quality to make tests pass; fixed tests must provide meaningful assertions.

11. **Handle low-value test decisions** - **before removing any test**, present the case for removal with rationale; prefer rewriting if it covers important functionality; ensure no coverage gaps.

12. **Final validation**:
    ```bash
    make test
    ```
    Verify all tests pass with no failures or errors.

**Escalation pattern:** if struggling with any single test after 3 attempts, pause and report; request human assistance rather than spending excessive time without guidance.

**Key principles:** quality over speed; systematic prioritization; standards compliance; no coverage compromise (removals must be explicitly discussed).

Begin systematic test failure analysis and remediation now.
