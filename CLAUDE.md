# Claude Code Guidelines for FMVPU Project

## Comments
NEVER add comments that explain what was changed or reference previous states of the code. Comments should explain what the code does or why it does it, not what it used to do or how it changed. Avoid diff-specific comments that only make sense in the context of changes being made.

## Code Style
All imports must be placed at the top of the file, not inline within functions. Follow standard Python import ordering (standard library, third-party, local imports).

NEVER add imports inside functions - always place them at the top of the file.

## Module Generation
**IMPORTANT**: When creating new modules with ModuleGenerator objects, you MUST add them to the case statement in `src/main/scala/fmvpu/Main.scala`.

## Testing
When running Python tests, always redirect output to a file so you can examine the complete output without needing to rerun the test. For example:
```bash
python python/fmvpu/amlet_test/test_alu_basic.py > test_output.log 2>&1
```
This allows you to read the file multiple times to analyze different parts of the output.

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
Then run the DSE flows using bazel targets.

## Grep Tool Usage
When using the Grep tool for searching code:
- **DO NOT** put extra quotes inside the pattern parameter value
- **Use simple patterns** rather than overly complex regex when possible
- **Issue**: Patterns like `"predicate.*new PTaggedSource"` (with quotes inside) will search for literal quote characters
- **Solution**: Use clean patterns like `predicate.*new PTaggedSource` (without extra quotes)
- Simple patterns like `isLocal` work better than complex multi-part regex patterns