---
allowed-tools: Bash, Read, TodoWrite, Task
description: Prepare code for review with quality checks and analysis
argument-hint:
---

Prepare the current code for review following our quality standards:

## Code Review Preparation Process

Execute comprehensive review preparation:

1. **Use TodoWrite to plan review preparation** - Track all quality checks
   - Read `docs/CLAUDE.md` for AI behavior patterns and quality standards
   - Use sub-agent coordination for expert analysis

2. **Run mandatory quality checks** - Both must pass:
   ```bash
   make test   # full test suite (must pass)
   make lint   # code quality check (must pass with no output)
   ```
   **CRITICAL**: Address any failures before proceeding.

3. **Generate a change summary** - Document what was modified:
   ```bash
   git log --oneline --graph -10            # recent commits on this branch
   git diff staging...HEAD                   # diff against the base branch (PR target)
   git diff --name-only staging...HEAD       # changed files
   ```

4. **Use specialized review agents** - Get expert analysis (launch in parallel where applicable):
   - **test-engineer** agent: review test coverage and quality
   - **code-quality** agent: review coding-standards compliance and maintainability
   - **backend-dev** agent: review Django patterns (if applicable)
   - **frontend-dev** agent: review template/UI changes (if applicable)
   - **comment-reviewer** agent: review comment/docstring content (if comments changed)

5. **Identify potential issues** - Look for:
   - Code quality concerns
   - Security vulnerabilities
   - Performance implications
   - Breaking changes
   - Missing tests
   - Documentation gaps

6. **Create a review checklist** - Generate actionable items:
   - Code quality improvements needed
   - Test coverage gaps to address
   - Documentation updates required
   - Security considerations
   - Performance optimizations
   - Breaking-change documentation

7. **Generate a review summary** - Provide a comprehensive overview:
   - Summary of changes made
   - Key components modified
   - Quality metrics (tests passing, lint clean)
   - Potential risks or concerns
   - Reviewer guidance and focus areas

**Review preparation goals:**
- Ensure code meets our quality standards
- Identify potential issues before PR creation
- Provide comprehensive change documentation
- Generate reviewer guidance

**Current branch:** [Will be determined from git status]

Begin review preparation now.
