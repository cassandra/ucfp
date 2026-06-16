---
allowed-tools: Bash, Read, TodoWrite
description: Create GitHub issues using proper templates and conventions
argument-hint: [type] [title]
---

Create a GitHub issue of type "$0" with title "$1" using the proper templates and conventions:

## GitHub Issue Creation Process

1. **Use TodoWrite to plan issue creation** - Track template selection and validation

2. **Validate issue type and template** - Map the type to a template:

   ```
   bug        -> .github/ISSUE_TEMPLATE/bug_report.md
   feature    -> .github/ISSUE_TEMPLATE/feature_request.md
   docs       -> .github/ISSUE_TEMPLATE/documentation.md
   ops        -> .github/ISSUE_TEMPLATE/operations.md
   refactor   -> .github/ISSUE_TEMPLATE/refactor.md
   tests      -> .github/ISSUE_TEMPLATE/tests.md
   ```

3. **Validate title format** - Use the type prefix convention:
   ```
   bug:      "[Bug] Comment list times out on large articles"
   feature:  "[Feature] Add comment pagination"
   docs:     "[Docs] Document the env-var drift check"
   ops:      "[Ops] Improve Docker build performance"
   refactor: "[Refactor] Consolidate article status logic"
   tests:    "[Tests] Add view tests for the publish flow"
   ```

4. **Create the issue using the GitHub CLI**:
   ```bash
   case "$0" in
     bug) TEMPLATE="bug_report.md" ;;
     feature) TEMPLATE="feature_request.md" ;;
     docs) TEMPLATE="documentation.md" ;;
     ops) TEMPLATE="operations.md" ;;
     refactor) TEMPLATE="refactor.md" ;;
     tests) TEMPLATE="tests.md" ;;
     *) echo "Invalid issue type: $0"; exit 1 ;;
   esac

   gh issue create --template "$TEMPLATE" --title "$1"
   ```

5. **Verify creation**:
   ```bash
   gh issue list --limit 1 --state open
   ```

6. **Provide issue information** - Return: the issue number and URL, the corresponding branch-naming pattern, and the next step (`/pickup <number>`).

## Issue Type Guidelines

| Type | Template | Title prefix | Branch | Use for |
|------|----------|--------------|--------|---------|
| `bug` | `bug_report.md` | `[Bug]` | `bugfix/##-description` | Unexpected behavior, errors, failures |
| `feature` | `feature_request.md` | `[Feature]` | `feature/##-description` | New functionality, enhancements |
| `docs` | `documentation.md` | `[Docs]` | `docs/##-description` | Documentation improvements |
| `ops` | `operations.md` | `[Ops]` | `ops/##-description` | CI/CD, deployment, infrastructure, tooling |
| `refactor` | `refactor.md` | `[Refactor]` | `refactor/##-description` | Code-quality improvements, no behavior change |
| `tests` | `tests.md` | `[Tests]` | `tests/description` (no issue number required) | Test coverage and quality |

## Quality Validation

- **Title**: must include the type prefix and be descriptive and specific (avoid generic titles).
- **Template**: verify the file exists under `.github/ISSUE_TEMPLATE/`; templates apply their labels automatically.
- **Branch naming**: provide the corresponding `git checkout -b <type>/<number>-<mnemonic>` guidance.

## Error Handling

- **Invalid issue type** (`$0` matches no template): list the available types and suggest the closest match.
- **Invalid title format** (`$1`): show the expected format and an example for the type.
- **`gh issue create` fails**: verify GitHub authentication, repository permissions, and template existence.

## Next Steps

After creation, pick the issue up for implementation with `/pickup <number>`.

**Issue Type:** $0
**Title:** "$1"

Begin the GitHub issue creation process now.
