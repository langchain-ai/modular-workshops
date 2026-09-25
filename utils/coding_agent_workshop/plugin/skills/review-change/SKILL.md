---
name: review-change
description: Review a task-tracker implementation against an issue's acceptance criteria, looking for missed requirements and missing tests. Use for reviews rather than making a fix.
---

# Review a task-tracker change

1. Read the requested issue with `mcp__plugin_workshop_issues__get_issue` and its criteria with `mcp__plugin_workshop_issues__get_acceptance_criteria`.
2. Read the implementation and tests in the current working directory. Run `python3 -m unittest -v` unless the user requested a read-only inspection without execution.
3. Check each acceptance criterion. Passing existing tests does not prove that an untested requirement is implemented.
4. Return concrete findings with file references, the observed test result, and a recommendation: ready, needs changes, or insufficient evidence.

Leave files unchanged during review. Do not commit, push, install packages, or inspect files outside the provided sample repository.
