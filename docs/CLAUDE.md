# CLAUDE.md

This file provides AI-specific guidance for Claude Code when working with this repository.

## Key Philosophy - Our Prime Directive

In all code we write, we strive for extremely well factored code. We are thoughtful about responsibility boundaries, encapsulation, readability and maintainability. We do not write the first code we can think of to solve the problem - we find a well factored version that does the job. We avoid assumptions and seek clarification and verification before acting.

## Custom Command Ecosystem

This project has custom commands for workflow automation. Use them proactively; the detailed specifications live in `.claude/commands/*.md`.

### Start of work
- **`/createissue type "title"`** - Create a GitHub issue with the proper template
- **`/pickup 123`** - Issue assignment and branch setup

### Quality and maintenance
- **`/commit "message"`** - Smart commits following project standards
- **`/comments`** - Pre-PR comment content analysis and rewrites (the commenting cleanup pass)
- **`/review`** - Pre-PR quality preparation with expert analysis
- **`/pr "title"`** - Pull request creation with the project template
- **`/fixtests`** - Test failure analysis and remediation
- **`/cleanup branch`** - Post-merge branch cleanup

### Specialized
- **`/refactor Class`** - Expert refactoring planning
- **`/release 1.2.3`** - Release process automation
- **`/icon "concept"`** - Find an existing icon or create a new one

## AI-Specific Guidelines

### Task Tracking
- Use the task-tracking tool for complex, multi-step work: plan before executing, track progress throughout, and mark tasks complete as you finish them.

### Sub-Agent Coordination
- **Use the specialized agents proactively** - they provide expert-level analysis.
- **Launch agents in parallel** when possible for efficiency.
- **Be specific about scope** - detailed context yields better results.
- **Chain agents** - use the output of one as input to another.

**Available agents:** `general-purpose`, `backend-dev`, `frontend-dev`, `test-engineer`, `code-quality`, `comment-reviewer`

### Project Documentation Structure
- **Authoritative docs:** `docs/dev/` contains the official workflow, testing, and coding standards, organized by role (`shared`, `backend`, `frontend`, `testing`, `workflow`).
- **Commands reference these docs** - don't duplicate their content.
- **When in doubt:** check `docs/dev/workflow/workflow-guidelines.md` for process questions.

### AI Behavior Patterns
- **Quality over speed** - use well-factored solutions, not the fastest working code.
- **Reference documentation** - commands point to authoritative sources.
- **Escalate when stuck** - pause after a few attempts on a difficult problem and ask.
- **No AI attribution** - keep commit messages and PR descriptions project-focused.

## Core Development Standards

### Quality Gates (Enforced by Commands)
- **`make lint`** must pass before any PR (`make check` runs lint + test + env-drift-check together).
- **`make test`** must pass before any PR.
- **Use project templates** for PRs (`.github/PULL_REQUEST_TEMPLATE.md`) and Issues (`.github/ISSUE_TEMPLATE/*`).

### Essential Technical Requirements
- **All imports at file top** (never inside functions/methods).
- **Use `/bin/rm` not `rm`** (avoid interactive prompts).

## Tone and Behavior
- **Criticism is welcome** - Please tell me when I am wrong or mistaken, or even when you think I might be wrong or mistaken.
- **Correct** - Please tell me if there is a better approach than the one I am taking.
- **Be concise** - I will let you know when I need longer explanations.
- **Do not flatter** - Do not give compliments unless I am specifically asking for your judgement.
- **Ask** - Feel free to ask many questions. If you are in doubt of my intent, don't guess. Ask.

## Key Project References

- **Project Structure** - `docs/dev/shared/project-structure.md`
- **Workflow:** `docs/dev/workflow/workflow-guidelines.md`
- **Testing:** `docs/dev/testing/testing-guidelines.md`
- **Coding Standards:** `docs/dev/shared/coding-standards.md`
- **Commenting:** `docs/dev/shared/commenting-guidelines.md`

Commands automatically reference these documents - no need to read them manually unless working outside the command workflows.
