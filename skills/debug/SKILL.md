---
name: debug
triggers:
  - debug
  - error
  - traceback
  - exception
  - bug
  - failing
  - broken
description: Systematic debugging approach for errors and bugs.
---

# Debug Skill

When the user reports a bug or error:

1. **Reproduce**: Understand how to trigger the issue. Ask for steps if unclear.
2. **Read the error**: Parse tracebacks and error messages carefully. Identify the file, line, and error type.
3. **Trace the cause**: Read the relevant source files. Follow the call chain from the error back to the root cause.
4. **Hypothesize**: Form a theory about what's wrong before making changes.
5. **Fix**: Make the minimal change that fixes the issue.
6. **Verify**: Run the failing command again to confirm the fix works.

**Principles:**
- Don't guess — read the code.
- Fix root causes, not symptoms.
- One fix at a time, then verify.
