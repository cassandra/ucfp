---
allowed-tools: Bash, Read, Write, TodoWrite
description: Create pull request following our workflow and template requirements
argument-hint: [title]
---

Create pull request with title "$0" following our workflow from `docs/dev/workflow/workflow-guidelines.md`:

## Pull Request Creation Process

Execute the complete PR creation workflow:

1. **Use TodoWrite to plan PR creation steps** - Track all required checks

2. **MANDATORY pre-PR requirements** - Both must pass before PR creation:
   ```bash
   make test   # full test suite (must pass)
   make lint   # code quality check (must pass with no output)
   ```
   **CRITICAL**: Do not create the PR if either check fails. Fix all issues first.

3. **Gather PR information** - Collect required details:
   - Current branch name and recent commits
   - **Detect the correct base branch** using `git remote show origin` to find the HEAD branch
   - Related GitHub issue number(s)
   - Summary of changes made
   - Testing performed
   - Documentation updates needed

4. **Create PR using GitHub CLI** - Follow the exact template from `.github/PULL_REQUEST_TEMPLATE.md`:

   **CRITICAL**: Use a file-based approach to prevent escaping failures:
   ```bash
   # Detect the correct base branch from remote HEAD
   BASE_BRANCH=$(git remote show origin | grep 'HEAD branch:' | cut -d' ' -f5)
   if [ -z "$BASE_BRANCH" ]; then
     echo "Warning: Could not detect base branch, falling back to 'staging'"
     BASE_BRANCH="staging"
   fi
   echo "Using base branch: $BASE_BRANCH"

   # Write PR body to a temporary file first
   cat > /tmp/pr_body.md <<'EOF'
   ## Pull Request: [TITLE]

   ### Issue Link
   Closes #[ISSUE_NUMBER]

   ---

   ## Category
   - [ ] **Feature** (New functionality)
   - [ ] **Bugfix** (Fixes an issue)
   - [ ] **Docs** (Documentation updates)
   - [ ] **Ops** (Infrastructure, CI/CD, build tools)
   - [ ] **Tests** (Adding/improving tests)
   - [ ] **Refactor** (Code improvements without changing functionality)
   - [ ] **Tweak** (Minor UI or code improvements)

   ---

   ## Changes Summary
   - [Describe changes made]

   ---

   ## How to Test
   1. [Testing steps]

   ---

   ## Checklist
   - [x] Code follows the project's style guidelines.
   - [x] Unit tests added or updated if necessary.
   - [x] All tests pass (`./manage.py test`).
   - [ ] Docs updated if applicable.
   - [x] No breaking changes introduced.

   ---

   ## Related PRs

   ---

   ## Screenshots (if applicable)

   ---

   ## Additional Notes

   ---

   ### **Ready for Review?**
   - [x] This PR is ready for review and merge.
   - [ ] This PR requires more work before approval.

   ---

   ### **Reviewer(s)**
   @cassandra
   EOF

   # Update placeholders in the file
   sed -i '' "s/\[TITLE\]/$0/g" /tmp/pr_body.md
   sed -i '' "s/\[ISSUE_NUMBER\]/ISSUE_NUMBER/g" /tmp/pr_body.md

   # Create PR using the file reference with the detected base branch
   gh pr create --title "$0" --body-file /tmp/pr_body.md --base "$BASE_BRANCH"

   # Clean up the temporary file
   rm -f /tmp/pr_body.md
   ```

5. **Verify PR creation** - Check that:
   - The PR was created successfully
   - Template formatting is correct
   - All required sections are filled
   - The proper category is selected
   - The issue is properly linked

**Requirements:**
- Follow the exact workflow from `docs/dev/workflow/workflow-guidelines.md`
- Use the exact template from `.github/PULL_REQUEST_TEMPLATE.md`
- **Automatically detect the base branch** - never assume; always detect from remote HEAD (falling back to `master`)
- Must pass all pre-PR checks before creation
- Use HEREDOC syntax to prevent formatting issues
- No AI attribution in the PR description

**PR Title:** "$0"

Begin the PR creation process now.
