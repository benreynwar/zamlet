# Claude Code Guidelines for RISC-V Model

## Essential Documentation

Before working on this code, read these documents to understand the system:

1. **LAMLET_ARCHITECTURE.md** - System architecture, component hierarchy, data flow patterns
2. **LOGGING.txt** - All logging labels, formats, and how to trace operations through the system
3. **COMPARING_WITH_TEST.txt** - Techniques for verifying simulator behavior matches expected test results

## Creating summary
When cache is running out, I'll ask you to create a summary to restart from.
The purpose of this summary is so that you can continue to work on resolving the problem.
What you have already done is irrelevant. What is important is what is left to do.
Don't be confident about the reasons for things when debugging. You're often wrong and we don't want
to bias the fresh context.

DO NOT include:
- Recent fixes or changes made during this session
- Explanations of bugs that were found and fixed
- Code snippets of changes

DO include:
- Current test status (what passes, what fails)
- The specific failure being investigated
- How to reproduce the failure
- Relevant file paths

## Running Tests
Always redirect test output to a log file in the current directory, then examine the log. This allows
you to search for specific log labels (see LOGGING.txt) without re-running the test:
```bash
python tests/conditional/test_conditional_kamlet.py --vector-length 32 > test.log 2>&1
grep "RF_WRITE" test.log
```

## Keeping this up-to-date
If you notice this file is not up-to-date, mention that, and suggest changes. Also keep the files this is
referencing up-to-date.
