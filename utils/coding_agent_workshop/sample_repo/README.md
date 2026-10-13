# Task tracker

This is Module 6's deliberately broken sample application. It uses only Python's standard library.

Run the tests:

```bash
python3 -m unittest -v
```

Two tests initially fail. Fetch **TASK-001** and its acceptance criteria using the workshop MCP tools, then use the `workshop:fix-bug` skill to fix them.

Run the application against a fixed date:

```bash
python3 tracker.py --today 2026-01-15
```

The later **TASK-002** exercise adds an ordering requirement. Fetch its criteria separately; passing TASK-001's tests does not prove TASK-002 is complete.

Work in the fresh copy created by the notebook. To repeat the exercise, create another copy instead of resetting your changes.
