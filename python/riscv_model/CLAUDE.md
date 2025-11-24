# Claude Code Guidelines for RISC-V Model

## Essential Documentation

Before working on this code, read these documents to understand the system:

1. **ARCHITECTURE.md** - System architecture, component hierarchy, data flow patterns
2. **logging.txt** - All logging labels, formats, and how to trace operations through the system
3. **comparing_with_test.txt** - Techniques for verifying simulator behavior matches expected test results

## Creating summary
When cache is running out, I'll ask you to create a summary to restart from.
The purpose of this summary is so that you can continue to work on resolving the problem.
What you have already done is irrelevant. What is important is what is left to do.
Don't be confident about the reasons for things when debugging.  You're often wrong and we don't want
to bias the fresh context.
