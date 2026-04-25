---
name: wrap-up
description: Update RESTART.md to seed the next session. Use when the user says "wrap up this context", invokes /wrap-up, asks to update RESTART.md, save state, prepare a fresh context, or create/revise a restart handoff after implementation, debugging, validation, or planning work.
---

Update `RESTART.md` at the repo root. It will be used to initialize the next
session.

The purpose is to let the next session continue the work without needing chat
history. Optimize for what remains to do, current validation state, and why the
work matters.

## Workflow

1. Read the existing `RESTART.md` first.
2. Inspect current state with lightweight commands such as `git status --short`,
   `git diff --stat`, relevant diffs, and any user-provided test results.
3. Preserve durable roadmap, big-picture goals, stable constraints, and
   longer-term tracked items unless the user explicitly says to remove them.
4. Remove or compress stale debugging archaeology when it no longer guides the
   next session. Completed blockers should not remain as the "immediate task".
5. Update the immediate next task so a fresh session can start work directly.
6. Include exact commands that remain useful: focused repros, validation
   commands, and aggregate tests. Do not include commands for resolved failures
   unless they are useful regression checks.
7. Update relevant files to favor what the next session should read first.
8. Make targeted edits to the existing file. Do not delete and recreate the
   handoff unless the user explicitly asks for a rewrite.

## Do NOT include
- Long postmortems for fixed bugs
- Stale "current failure" sections after the failure is resolved
- Commands for resolved failures unless they remain useful regression tests
- Code snippets of changes unless they are essential to the next task

## DO include
- **The big picture goal** — what are we ultimately trying to achieve? Reference
  `docs_llm/ROADMAP.md`, `docs_llm/plan_status.md`, and any specific
  `docs_llm/plans/PLAN_*.md` files. This is the most important part — don't lose
  sight of why we're doing something.
- Current test status (what passes, what fails)
- The source of test status when known, e.g. "user reported passing" versus
  "verified locally"
- The specific failure being investigated (if debugging)
- How to reproduce the failure
- Relevant file paths
- What step of the plan we're on (if following a plan)
- User decisions and preferences that affect future work

RESTART.md should let a fresh context understand both *what* we're doing and *why*.
Start with the big picture, then narrow down to the current task.

## Preserve scope across sessions
The big picture often already exists in `RESTART.md` from when the session started.
Preserve it — the scope should not narrow from one session to the next. If the
session started with a goal like "implement monitoring system", don't reduce it to
just "fix this one bug".

## Suggested structure

Use this structure when it fits the repo, while preserving useful existing
sections:

```markdown
# RESTART: <current next task>

## Big picture
Durable project goal and roadmap links.

## Immediate task
The next concrete work item, with design notes needed to start.

## Current validation state
What passes/fails now, with exact commands.

## Relevant files for next session
Files grouped by purpose, biased toward what to read first.

## Longer-term tracked items
Durable backlog items that should survive session turnover.
```
