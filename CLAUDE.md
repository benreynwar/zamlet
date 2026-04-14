# Claude Code Guidelines for FMVPU Project

## TODOs
`docs/TODO.md` tracks known issues and future work. Check it when relevant.

## Plans
Plans may be stored in either `.claude/plans/` (project-local) or `~/.claude/plans/` (global).
Check both locations when looking for a plan file.

## Development Environment (Nix)
This project uses Nix for dependency management. Enter the development shell with:
```bash
nix-shell
```

**IMPORTANT**: Before running any commands (tests, bazel, python, etc.), verify you are inside
the nix-shell by checking for the `IN_NIX_SHELL` environment variable (`echo $IN_NIX_SHELL`).
If not in nix-shell, enter it first. The nix-shell working directory is the repo root.

The nix shell provides:
- EDA tools: OpenROAD, Yosys, Magic, Verilator, KLayout
- Python with librelane package installed
- Bazel, JDK, Scala tooling
- PDK_ROOT and PDK environment variables set for sky130A

The `shell.nix` pulls librelane from GitHub and applies local patches. For local librelane
development, uncomment the local path override in `shell.nix`.

The librelane source code is available at `~/Code/librelane` for reference (not the version used
by the project, but useful for understanding the code).

The Chisel source code is available at `~/Code/chisel` (the `~/Code` directory itself is the
chisel repo root). Useful for understanding Chisel internals when debugging elaboration issues.

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
Do NOT run large test suites (e.g. `bazel test //python/zamlet/tests:all_tests` or
`//python/zamlet/kernel_tests:all_tests`). The user will run those. You can run individual
tests or small groups of tests yourself.

When running Python tests, always redirect output to a file so you can examine the complete output without needing to rerun the test. For example:
```bash
python python/zamlet/tests/test_strided_store.py -g k2x2_j1x2 --ew=32 --vl=127 \
  --stride=3657 --seed=14 > test_output.log 2>&1
```
This allows you to read the file multiple times to analyze different parts of the output.

### Running tests directly (without pytest)
Tests in `python/zamlet/tests/` can be run directly with Python. Use `--list-geometries` to see
available configurations. Test names from pytest encode the parameters:

```
# pytest test name: test_strided_store[14_k2x2_j1x2_ew32_vl127_s3657]
# Format: {index}_{geometry}_ew{ew}_vl{vl}_s{stride}
# Decodes to: geometry=k2x2_j1x2, ew=32, vl=127, stride=3657, seed=14
python python/zamlet/tests/test_strided_store.py -g k2x2_j1x2 --ew=32 --vl=127 \
  --stride=3657 --seed=14 --dump-spans > tests/log.txt 2>&1
```

### Running Tests with Bazel
Tests are generated with config suffixes. To run a test using bazel:
```bash
bazel test //python/zamlet/kamlet_test:test_kamlet_default --test_output=streamed
bazel test //python/zamlet/lamlet_test:test_zamlet_default --test_output=streamed
```
The pattern is: `//python/zamlet/{module}_test:{test_name}_{config_name}`
Always use `--test_output=streamed` to see test output in real-time.

**IMPORTANT**: In cocotb tests, when setting signal values, you MUST use the `.value` attribute. For dynamic signal access, use `getattr` to get the signal object, then set its `.value`:
- Correct: `dut.io_writeInputs_0_valid.value = 0`
- Correct: `getattr(dut, f'io_writeInputs_{i}_valid').value = 0`
- Incorrect: `setattr(dut, 'io_writeInputs_0_valid', 0)`

## File Creation
When creating new files, especially large ones, create them in small chunks for review. Do not create entire large files at once.

## Area Analysis
To get area analysis for components, add them to the appropriate DSE BUILD file:
- For amlet components: Add to `dse/amlet/BUILD` in the `AMLET_STUDIES` list
- For bamlet components: Add to `dse/bamlet/BUILD` in the `BAMLET_STUDIES` list

Run DSE flows using: `bazel build //dse/{component}:{study_name}__{pdk}_results`
Example: `bazel build //dse/bamlet:Bamlet_default__asap7_results`

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

## Grep Tool Usage
When using the Grep tool for searching code:
- **DO NOT** put extra quotes inside the pattern parameter value
- **Use simple patterns** rather than overly complex regex when possible
- **Issue**: Patterns like `"predicate.*new PTaggedSource"` (with quotes inside) will search for literal quote characters
- **Solution**: Use clean patterns like `predicate.*new PTaggedSource` (without extra quotes)
- Simple patterns like `isLocal` work better than complex multi-part regex patterns

## Task Ordering
If you think a different order or approach would be better than what was asked, suggest it
and discuss — don't just start doing something else without checking in first.

## Communication Style
When I ask you to show me something (e.g., grep output, log excerpts), just show it and wait.
Don't continue with analysis unless I ask for it.

NEVER claim success with phrases like "The key achievement is" or similar when a task has failed.
Be honest about failures and focus on what still needs to be done rather than trying to spin
partial progress as success. This is irritating and unhelpful.

NEVER declare a task "successfully complete" or use similar language until the actual end goal is achieved. Making incremental progress (like builds completing or components initializing) is not the same as task completion. The task is only complete when the final success criteria are met (e.g., tests pass, features work end-to-end). Premature success declarations are frustrating and misleading.

We are working on this together - this is collaborative work. When you encounter something difficult, do NOT skip it or use placeholder values. Instead, explain what is difficult so we can discuss and solve it together. Many parts will be too hard to do alone and that's expected.

## Wrapping up context
When I say "wrap up this context", write a short summary of where we are at to RESTART.md. This will be used to initialize the next session. Follow the guidelines below.

The purpose of this summary is so that you can continue to work on resolving the problem. What you have already done is irrelevant. What is important is what is left to do. Don't be confident about the reasons for things when debugging. You're often wrong and we don't want to bias the fresh context.

DO NOT include:
- Recent fixes or changes made during this session
- Explanations of bugs that were found and fixed
- Code snippets of changes

DO include:
- **The big picture goal** - What are we ultimately trying to achieve? Reference any PLAN_*.md files. This is the most important part - don't lose sight of why we're doing something.
- Current test status (what passes, what fails)
- The specific failure being investigated (if debugging)
- How to reproduce the failure
- Relevant file paths
- What step of the plan we're on (if following a plan)

The RESTART.md should allow a fresh context to understand both *what* we're doing and *why*. Start with the big picture, then narrow down to the current task.

**Important**: The big picture often already exists in RESTART.md from when the session started. Preserve it - the scope should not narrow from one session to the next. If the session started with a goal like "implement monitoring system", don't reduce it to just "fix this one bug".

## Debugging bazel out

When debugging Bazel builds, you need to search within the `bazel-out` directory from inside that directory:

```bash
# Wrong - won't work from project root:
find bazel-out -name "*cocotb*" -type f

# Correct - change directory first:
cd bazel-out && find . -name "*cocotb*" -type  f
