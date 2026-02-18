---
name: commit
triggers:
  - commit
  - git commit
  - save changes
  - stage changes
description: Guide the agent through creating a well-formed git commit.
---

# Commit Skill

When the user asks you to commit changes:

1. Run `git status` to see what's changed.
2. Run `git diff` to review the actual changes.
3. Analyze the changes and draft a concise commit message:
   - Use imperative mood ("Add feature" not "Added feature").
   - First line under 72 characters.
   - Summarize the "why", not just the "what".
4. Stage the relevant files with `git add` (prefer specific files over `git add .`).
5. Show the user the proposed commit message and ask for confirmation.
6. Create the commit.

**Important:** Never force-push or amend commits without explicit permission.
