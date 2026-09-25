---
name: fix-bug
description: Fix a task-tracker bug using an issue's acceptance criteria and regression tests. Also use this skill to investigate a bug without editing when the user requests inspection only.
---

# Fix a task-tracker bug

1. Read the requested issue with `mcp__plugin_workshop_issues__get_issue` and its criteria with `mcp__plugin_workshop_issues__get_acceptance_criteria`. Ask for an issue ID if the user did not provide one.
2. Inspect the relevant source and tests in the current working directory.
3. If the user requested inspection only, explain the discrepancy and stop before editing or running tests.
4. Otherwise, reproduce the issue with `python3 -m unittest -v`, make the smallest change that meets the criteria, and add a regression test for any requirement not already covered.
5. Run the tests again. Summarize the change, the observed test result, and any remaining requirements. Report missing evidence rather than claiming an unrun test passed.

Work only in the provided sample repository. Do not commit, push, install packages, or modify files outside it.
