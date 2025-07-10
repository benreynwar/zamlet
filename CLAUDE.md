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