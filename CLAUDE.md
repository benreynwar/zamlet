# Claude Code Guidelines for FMVPU Project

## Planning docs
- `docs_llm/ROADMAP.md` — big-picture milestones.
- `docs_llm/plan_status.md` — one-line index of plans in `docs_llm/plans/`.
- `docs_llm/TODO.md` — smaller known issues and follow-ups.

## Worktree layout
This checkout is one of several sibling worktrees under `~/Projects/zamlet/` (e.g.
`main`, `fft`, `memlet`, `rvv_python`), backed by a shared bare repo at `.bare`. To
inspect another branch's state without checking it out, read directly from the sibling
path. `RESTART.md` is per-worktree.

## Memory
The `memory/` directory under `~/.claude/projects/` is symlinked across all zamlet
worktrees, so memory is shared. Multiple sessions may run in parallel, so do not
write branch-specific or transient state to memory — it bleeds across worktrees and
can race with concurrent writes.

## Development Environment (Nix)
This project uses Nix for dependency management. Enter the development shell with
`nix-shell`. See `shell.nix` for what the environment provides.

**IMPORTANT**: Before running any commands (tests, bazel, python, etc.), verify you are
inside the nix-shell by checking `echo $IN_NIX_SHELL`. If not in nix-shell, enter it first.

Reference checkouts (external to this repo):
- Chisel source: `~/Code/chisel`
- librelane source: `~/Code/librelane`

## Comments
NEVER add comments that explain what was changed or reference previous states of the code. Comments should explain what the code does or why it does it, not what it used to do or how it changed. Avoid diff-specific comments that only make sense in the context of changes being made.

NEVER remove existing comments when editing code unless you are intentionally removing them and explaining why. When rewriting a block of code, preserve all existing comments that are still relevant.

## Defensive Coding
DO NOT add `if x is None` or `if x is not None` checks that silently handle unexpected states.
This hides serious bugs. If a value should never be None, access it directly and let it fail
with a clear error if the assumption is wrong.

DO NOT remove assert statements when tidying or refactoring code. Assert statements are valuable
for catching bugs early. When cleaning up code, always preserve existing assert statements.

Make liberal use of assert statements — failing with good error messages is useful. Prefer
asserting expected conditions over defensive if-checks that silently handle unexpected states.

## Code Style
All imports must be placed at the top of the file, not inline within functions. Follow standard
Python import ordering (standard library, third-party, local imports).

NEVER add imports inside functions - always place them at the top of the file.

## Line Width
All code and documentation should be formatted to a maximum line width of 100 columns. This improves readability and ensures consistent formatting across the codebase.

## Writing Style
Avoid unnecessary marketing/promotional words like "comprehensive", "robust", "powerful", "cutting-edge", etc. unless they are truly necessary for technical accuracy. Prefer clear, direct language.

## Quoting Sources
NEVER paraphrase when using quote marks. If you use quotation marks, the text must be verbatim from the source. If you need to summarize or paraphrase, do not use quote marks.

## References
NEVER add a reference (e.g., "Reference: riscv-isa-manual/src/f-st-ext.adoc") without first
reading the referenced document to verify it is correct. Don't guess which document something
is in based on naming patterns.

## RISC-V ISA Manual Location
The RISC-V ISA manual is located at `~/Code/riscv-isa-manual`. The vector extension spec is at:
```
~/Code/riscv-isa-manual/src/v-st-ext.adoc
```

## Running Commands
Never pipe command output through `head` or `tail` if you might need to see more of it later - this forces re-running the command. Either:
1. Run the command and wait for full output
2. Redirect to a file first, then read the file

## Testing
Do NOT run large test suites (`//python/zamlet/tests:all_tests`,
`//python/zamlet/kernel_tests:all_tests`, etc.) — the user runs those. Run individual
tests or small groups yourself, and redirect output to a file so you can re-read it.

Python tests in `python/zamlet/tests/` run directly (not just via pytest). Pytest
names encode parameters, e.g. `test_strided_store[14_k2x2_j1x2_ew32_vl127_s3657]` →
`-g k2x2_j1x2 --ew=32 --vl=127 --stride=3657 --seed=14`. Use `--list-geometries`
to see geometry options.

Bazel test pattern: `//python/zamlet/{module}_test:{test_name}_{config_name}`. Always
pass `--test_output=streamed`.

**Cocotb signal writes**: assign via `.value` (`dut.io_foo.value = 0`), never
`setattr`. For dynamic names use `getattr(dut, name).value = 0`.

## Area Analysis
DSE studies live under `dse/{jamlet,kamlet,lamlet,memlet,maths,network}/BUILD` as
individual `chisel_dse_module` targets. Add a new target there to get area analysis
for a component.

Run DSE flows: `bazel build //dse/{component}:{target_name}__{pdk}_results`
Example: `bazel build //dse/kamlet:Kamlet_default__sky130hd_results`

## Git
NEVER use `git stash`. If you need to test the original code, discuss it with me first.

## Bazel
NEVER run `bazel clean` or `bazel clean --expunge` unless explicitly told to by the user.

## Chisel
NEVER use the `%` (modulo) operator in Chisel code. It synthesizes to expensive divider hardware. Use bit masking instead when the divisor is a power of 2 (e.g., `x & (n-1).U` instead of `x % n.U`).

## Bug Investigation
When you find and fix a bug, always search for similar bugs elsewhere in the codebase:
- If the bug is in a pattern (e.g., missing page alignment), grep for similar patterns
- If it's in one of a pair of functions (e.g., load_stride/store_stride), check the counterpart
- If it's in test code, check other test files for the same issue
- Document the search you did and what you found

## Task Ordering
If you think a different order or approach would be better than what was asked, suggest it
and discuss — don't just start doing something else without checking in first.

## Communication Style
When I ask to see something (grep output, log excerpts), just show it and wait. Don't
continue with analysis unless I ask.

Don't declare success until the real end goal is achieved — incremental progress
(builds green, components initialising) is not the same as task completion. Be
honest about failures and focus on what still needs to be done; do not spin partial
progress as success.

This is collaborative work. When you hit something difficult, do NOT skip it or use
placeholder values — explain what's difficult so we can solve it together.

## Wrapping up context
When I say "wrap up this context" (or you invoke `/wrap-up`), use the `wrap-up` skill.

## Debugging bazel out

When debugging Bazel builds, you need to search within the `bazel-out` directory from inside that directory:

```bash
# Wrong - won't work from project root:
find bazel-out -name "*cocotb*" -type f

# Correct - change directory first:
cd bazel-out && find . -name "*cocotb*" -type  f
