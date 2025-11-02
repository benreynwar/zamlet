# Claude Code Guidelines for FMVPU Project

## Comments
NEVER add comments that explain what was changed or reference previous states of the code. Comments should explain what the code does or why it does it, not what it used to do or how it changed. Avoid diff-specific comments that only make sense in the context of changes being made.

## Code Style
All imports must be placed at the top of the file, not inline within functions. Follow standard Python import ordering (standard library, third-party, local imports).

NEVER add imports inside functions - always place them at the top of the file.

## Line Width
All code and documentation should be formatted to a maximum line width of 100 columns. This improves readability and ensures consistent formatting across the codebase.

## Writing Style
Avoid unnecessary marketing/promotional words like "comprehensive", "robust", "powerful", "cutting-edge", etc. unless they are truly necessary for technical accuracy. Prefer clear, direct language.

## Module Generation
**IMPORTANT**: When creating new modules with ModuleGenerator objects, you MUST add them to the case statement in `src/main/scala/zamlet/Main.scala`.

## Testing
When running Python tests, always redirect output to a file so you can examine the complete output without needing to rerun the test. For example:
```bash
python python/zamlet/amlet_test/test_alu_basic.py > test_output.log 2>&1
```
This allows you to read the file multiple times to analyze different parts of the output.

**IMPORTANT**: DO NOT use `timeout` command when running tests. If a test hangs, the user will interrupt it manually.

### Running Tests with Bazel
Tests are generated with config suffixes. To run a test using bazel:
```bash
bazel test //python/zamlet/bamlet_test:test_basic_default --test_output=streamed
bazel test //python/zamlet/amlet_test:test_alu_basic_default --test_output=streamed
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

## Grep Tool Usage
When using the Grep tool for searching code:
- **DO NOT** put extra quotes inside the pattern parameter value
- **Use simple patterns** rather than overly complex regex when possible
- **Issue**: Patterns like `"predicate.*new PTaggedSource"` (with quotes inside) will search for literal quote characters
- **Solution**: Use clean patterns like `predicate.*new PTaggedSource` (without extra quotes)
- Simple patterns like `isLocal` work better than complex multi-part regex patterns

## Communication Style
NEVER claim success with phrases like "The key achievement is" or similar when a task has failed. Be honest about failures and focus on what still needs to be done rather than trying to spin partial progress as success. This is irritating and unhelpful.

NEVER declare a task "successfully complete" or use similar language until the actual end goal is achieved. Making incremental progress (like builds completing or components initializing) is not the same as task completion. The task is only complete when the final success criteria are met (e.g., tests pass, features work end-to-end). Premature success declarations are frustrating and misleading.

## Debugging bazel out

When debugging Bazel builds, you need to search within the `bazel-out` directory from inside that directory:

```bash
# Wrong - won't work from project root:
find bazel-out -name "*cocotb*" -type f

# Correct - change directory first:
cd bazel-out && find . -name "*cocotb*" -type  f
