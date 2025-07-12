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
python test/main/python/fmvpu/test_lane.py > test_output.log 2>&1
```
This allows you to read the file multiple times to analyze different parts of the output.

**IMPORTANT**: In cocotb tests, when setting signal values, you MUST use the `.value` attribute. For dynamic signal access, use `getattr` to get the signal object, then set its `.value`:
- Correct: `dut.io_writeInputs_0_valid.value = 0`
- Correct: `getattr(dut, f'io_writeInputs_{i}_valid').value = 0`
- Incorrect: `setattr(dut, 'io_writeInputs_0_valid', 0)`

## File Creation
When creating new files, especially large ones, create them in small chunks for review. Do not create entire large files at once.