---
name: wrap-up
description: Write RESTART.md to seed the next Claude session. Use when the user says "wrap up this context" or invokes /wrap-up.
---

Write a short summary of where we are to `RESTART.md` at the repo root. This will be
used to initialize the next session.

The purpose of this summary is so that the next session can continue resolving the
problem. What has already been done is irrelevant. What is important is what is left
to do. Don't be confident about the reasons for things when debugging — you're often
wrong and we don't want to bias the fresh context.

## Do NOT include
- Recent fixes or changes made during this session
- Explanations of bugs that were found and fixed
- Code snippets of changes

## DO include
- **The big picture goal** — what are we ultimately trying to achieve? Reference
  `docs_llm/ROADMAP.md`, `docs_llm/plan_status.md`, and any specific
  `docs_llm/plans/PLAN_*.md` files. This is the most important part — don't lose
  sight of why we're doing something.
- Current test status (what passes, what fails)
- The specific failure being investigated (if debugging)
- How to reproduce the failure
- Relevant file paths
- What step of the plan we're on (if following a plan)

RESTART.md should let a fresh context understand both *what* we're doing and *why*.
Start with the big picture, then narrow down to the current task.

## Preserve scope across sessions
The big picture often already exists in `RESTART.md` from when the session started.
Preserve it — the scope should not narrow from one session to the next. If the
session started with a goal like "implement monitoring system", don't reduce it to
just "fix this one bug".
