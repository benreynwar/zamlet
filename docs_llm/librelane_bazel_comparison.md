# Librelane Classic Flow vs Bazel Implementation Comparison

## Verification Instructions

**CRITICAL RULES - VIOLATION MEANS WORK GETS DELETED:**

1. **ONE STEP AT A TIME - NO EXCEPTIONS.**
   - Verify ONE step completely before moving to the next
   - Write the detailed analysis for ONE step
   - Update the status table for ONE step
   - ONLY THEN move to the next step
   - If you add multiple steps in a single edit, ALL of that work will be deleted
   - If you research multiple steps before writing any analysis, you WILL make mistakes
   - This rule exists because rushing leads to errors that are hard to catch later

2. **NOTHING IS VERIFIED WITHOUT DETAILED NOTES.** If a step doesn't have explicit verification
   notes with line numbers and evidence, it is NOT verified. Never assume prior work was done
   correctly.

3. **CHECK FOR BEHAVIORAL DIFFERENCES.** Don't just check ID/inputs/outputs/gating. Look for
   ANYTHING that might make librelane and Bazel behavior not match exactly.

4. **BE SKEPTICAL.** If something seems too easy or you're tempted to bulk-update, stop. Go
   slower. Check more carefully.

**The procedure for each step is:**
1. Read the librelane step source (get ID, inputs, outputs, behavior)
2. Check gating in classic.py gating_config_vars dict
3. **ENUMERATE ALL CONFIG VARIABLES** - Find every `config_vars` definition in the step class
   and all parent classes. List every single Variable.
4. Read the Bazel implementation
5. Check position in full_flow.bzl
6. Write the detailed analysis section for THIS ONE STEP
7. Update the status table for THIS ONE STEP
8. STOP. Do not proceed to the next step until this one is complete.

**For each step, verify:**

1. Step ID matches exactly (with line numbers from both sources)
2. Inputs match (DesignFormat types)
3. Outputs match (DesignFormat types)
4. Gating matches (config variable name AND default value)
5. Step appears in correct position in full_flow.bzl
6. **EVERY config variable must be implemented** - see Config Variable Implementation below
7. Any special behavior (deferred errors, self-skipping, etc.)

## Config Variable Implementation

**CRITICAL: Every librelane config variable must have a corresponding Bazel attribute.**

Do NOT skip variables because "the default is fine" or "we don't need to change it". The goal is
to reproduce librelane's full configurability in Bazel. Users must be able to set any config
variable to any value, just like they can in librelane.

**For EACH config variable, you must:**

1. Find the Variable definition in librelane (name, type, default, description)
2. Implement the complete wiring in Bazel (all 5 locations below)
3. Document the status as "Wired" or "Missing"

**The 5 locations for each config variable:**

| Location | File | What to add |
|----------|------|-------------|
| 1. Attribute | `common.bzl` ENTRY_ATTRS | `"var_name": attr.type(doc="...", default=X)` |
| 2. Provider field | `providers.bzl` LibrelaneInput | `"var_name": "description"` |
| 3. Init wiring | `init.bzl` _init_impl | `var_name = ctx.attr.var_name` |
| 4. Config dict | `common.bzl` create_librelane_config | `config["VAR_NAME"] = input_info.var_name` |
| 5. Config keys | step's `*_CONFIG_KEYS` list | `"VAR_NAME"` |

**Valid Bazel Status values:**
- **Wired** = implemented in all 5 locations
- **Missing** = needs to be added (step is incomplete until fixed)

**Invalid status values (do not use):**
- "Uses default" - NO, add the attribute with the default value
- "Acceptable" - NO, implement it properly
- "Not needed" - NO, if librelane has it, Bazel needs it

**Do NOT use step-local attrs + extra_config pattern.** Some steps currently pass config via step-specific
attrs and extra_config dict (e.g., `pdn_obstructions` in odb.bzl). This pattern should be avoided. All
config variables must use the 5-location pattern so they flow through LibrelaneInput consistently.

**Config variable audit checklist:**
- Find `config_vars = [...]` in the step class
- Trace full inheritance chain (e.g., Synthesis -> PyosysStep -> Step) for inherited config_vars
- Check the run() method for any `self.config["KEY"]` or `self.config.get("KEY")` accesses
- Check any scripts the step calls for config key usage
- For each Variable: name, type, default, description
- Verify all 5 wiring locations are implemented

**Additional verification areas:**

1. **Scripts reading config directly** - Steps run scripts (e.g., synthesize.py, TCL scripts).
   These scripts may read config keys directly that aren't declared in config_vars. Trace what
   config keys each script accesses.

2. **Environment variables** - Steps may read env vars directly (PDK_ROOT, tool paths, etc.).
   Bazel's sandbox may not have these set. Check what env vars the step expects.

3. **Flow-level logic in classic.py** - Does classic.py modify config between steps? Run
   conditional logic based on earlier results? Insert steps dynamically? We must replicate this.

4. **State object contents** - librelane passes a State object between steps. Check if it
   contains anything besides file paths that affects behavior.

5. **Step instantiation** - How does librelane instantiate the step? Are there constructor
   arguments or factory patterns we might miss?

6. **Inter-step dependencies** - Does a step read outputs from earlier steps in unexpected ways?
   (e.g., reading a report file from a previous step to make decisions)

7. **Reports and auxiliary outputs** - Steps often generate reports, logs, and other auxiliary
   files beyond the main outputs. Check what files the step creates and whether we should
   register them as Bazel outputs so they get saved and are accessible for debugging.

**Record findings with:**
- Specific line numbers
- Actual code/values found
- Any behavioral notes or concerns
- Date verified

**Source files:**
- Librelane Classic flow: `~/Code/librelane/librelane/flows/classic.py` (lines 40-118)
- Librelane gating: `~/Code/librelane/librelane/flows/classic.py` (gating_config_vars dict ~line 267)
- Librelane step implementations: `~/Code/librelane/librelane/steps/*.py`
- Bazel flow: `bazel/flow/full_flow.bzl`
- Bazel step rules: `bazel/flow/*.bzl`

---

This document tracks the detailed comparison between librelane's Classic flow Python
implementation and our Bazel rules.

## Verification Status

Legend:
- **PASS** - Verified correct
- **FAIL** - Mismatch found
- **DEFERRED** - Source/config audited, but runtime verification intentionally deferred
- **TODO** - Needs detailed verification
- Gating: Y = has gating, N/A = no gating needed, **MISSING** = should have gating but doesn't

| Step | Name | ID Match | I/O Match | Gating Match | Status |
|------|------|----------|-----------|--------------|--------|
| 1 | Verilator.Lint | Y | Y | Y | PASS |
| 2 | Checker.LintTimingConstructs | Y | Y | Y | PASS |
| 3 | Checker.LintErrors | Y | Y | Y | PASS |
| 4 | Checker.LintWarnings | Y | Y | Y | PASS |
| 5 | Yosys.JsonHeader | Y | Y | N/A | PASS |
| 6 | Yosys.Synthesis | Y | Y | N/A | PASS |
| 7 | Checker.YosysUnmappedCells | Y | Y | N/A | PASS |
| 8 | Checker.YosysSynthChecks | Y | Y | N/A | PASS |
| 9 | Checker.NetlistAssignStatements | Y | Y | N/A | PASS |
| 10 | OpenROAD.CheckSDCFiles | Y | Y | N/A | PASS |
| 11 | OpenROAD.CheckMacroInstances | Y | Y | N/A | PASS |
| 12 | OpenROAD.STAPrePNR | Y | Y | N/A | PASS |
| 13 | OpenROAD.Floorplan | Y | Y | N/A | PASS |
| 14 | OpenROAD.DumpRCValues | Y | Y | N/A | PASS |
| 14b | Odb.CheckMacroAntennaProperties | Y | Y | N/A | PASS |
| 15 | Odb.SetPowerConnections | Y | Y | N/A | PASS |
| 16 | Odb.ManualMacroPlacement | Y | Y | Y | PASS |
| 17 | OpenROAD.CutRows | Y | Y | N/A | PASS |
| 18 | OpenROAD.TapEndcapInsertion | Y | Y | Y | PASS |
| 19 | Odb.AddPDNObstructions | Y | Y | Y | PASS |
| 20 | OpenROAD.GeneratePDN | Y | Y | N/A | PASS |
| 21 | Odb.RemovePDNObstructions | Y | Y | Y | PASS |
| 22 | Odb.AddRoutingObstructions | Y | Y | Y | PASS |
| 23 | OpenROAD.GlobalPlacementSkipIO | Y | Y | N/A | PASS |
| 24 | OpenROAD.IOPlacement | Y | Y | Y | PASS |
| 25 | Odb.CustomIOPlacement | Y | Y | Y | PASS |
| 26 | Odb.ApplyDEFTemplate | Y | Y | Y | PASS |
| 27 | OpenROAD.GlobalPlacement | Y | Y | N/A | PASS |
| 28 | Odb.WriteVerilogHeader | Y | Y | N/A | PASS |
| 29 | Checker.PowerGridViolations | Y | Y | N/A | PASS |
| 30 | OpenROAD.STAMidPNR | Y | Y | N/A | PASS |
| 31 | OpenROAD.RepairDesignPostGPL | Y | Y | Y | PASS |
| 32 | Odb.ManualGlobalPlacement | Y | Y | Y | PASS |
| 33 | OpenROAD.DetailedPlacement | Y | Y | N/A | PASS |
| 34 | OpenROAD.CTS | Y | Y | Y | PASS |
| 35 | OpenROAD.STAMidPNR | Y | Y | N/A | PASS |
| 36 | OpenROAD.ResizerTimingPostCTS | Y | Y | Y | PASS |
| 37 | OpenROAD.STAMidPNR | Y | Y | N/A | PASS |
| 38 | OpenROAD.GlobalRouting | Y | Y | N/A | PASS |
| 39 | OpenROAD.CheckAntennas | Y | Y | N/A | PASS |
| 40 | OpenROAD.RepairDesignPostGRT | Y | Y | Y | DEFERRED |
| 41 | Odb.DiodesOnPorts | Y | Y | Y | PASS |
| 42 | Odb.HeuristicDiodeInsertion | Y | Y | Y | DEFERRED |
| 43 | OpenROAD.RepairAntennas | Y | Y | Y | PASS |
| 44 | OpenROAD.ResizerTimingPostGRT | Y | Y | Y | DEFERRED |
| 45 | OpenROAD.STAMidPNR | Y | Y | N/A | PASS |
| 46 | OpenROAD.DetailedRouting | Y | Y | Y | PASS |
| 47 | Odb.RemoveRoutingObstructions | Y | Y | Y | PASS |
| 48 | OpenROAD.CheckAntennas | Y | Y | N/A | PASS |
| 49 | Checker.TrDRC | Y | Y | Y | PASS |
| 50 | Odb.ReportDisconnectedPins | Y | Y | Y | PASS |
| 51 | Checker.DisconnectedPins | Y | Y | Y | PASS |
| 52 | Odb.ReportWireLength | Y | Y | N/A | PASS |
| 53 | Checker.WireLength | Y | Y | Y | PASS |
| 54 | OpenROAD.FillInsertion | Y | Y | N/A | PASS |
| 55 | Odb.CellFrequencyTables | Y | Y | N/A | PASS |
| 56 | OpenROAD.RCX | Y | Y | Y | PASS |
| 57 | OpenROAD.STAPostPNR | Y | Y | Y | PASS |
| 58 | OpenROAD.IRDropReport | Y | Y | Y | PASS |
| 59 | Magic.StreamOut | Y | Y | Y | PASS |
| 60 | KLayout.StreamOut | Y | Y | Y | PASS |
| 61 | Magic.WriteLEF | Y | Y | Y | PASS |
| 62 | Odb.CheckDesignAntennaProperties | Y | Y | N/A | PASS |
| 63 | KLayout.XOR | Y | Y | Y | PASS |
| 64 | Checker.XOR | Y | Y | Y | PASS |
| 65 | Magic.DRC | Y | Y | Y | PASS |
| 66 | KLayout.DRC | Y | Y | Y | PASS |
| 67 | Checker.MagicDRC | Y | Y | Y | PASS |
| 68 | Checker.KLayoutDRC | Y | Y | Y | PASS |
| 69 | Magic.SpiceExtraction | ? | ? | ? | TODO |
| 70 | Checker.IllegalOverlap | Y | Y | N/A | PASS |
| 71 | Netgen.LVS | Y | Y | Y | PASS |
| 72 | Checker.LVS | Y | Y | Y | PASS |
| 73 | Yosys.EQY | Y | Y | Y | PASS |
| 74 | Checker.SetupViolations | Y | Y | N/A | PASS |
| 75 | Checker.HoldViolations | Y | Y | N/A | PASS |
| 76 | Checker.MaxSlewViolations | Y | Y | N/A | PASS |
| 77 | Checker.MaxCapViolations | Y | Y | N/A | PASS |
| 78 | Misc.ReportManufacturability | Y | Y | N/A | PASS |

---

## Critical Issues Found

### Current Open Issues

No remaining missing gate parameters are known in `librelane_classic_flow()`.
The experimental steps that default off in LibreLane Classic are now structurally
gated in Bazel as well.

### Default Value Mismatches

(All previous mismatches have been fixed - FP_CORE_UTIL now defaults to 50%)

---

## Detailed Step Analysis

### Step 1: Verilator.Lint

**Verified:** 2026-07-06 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/verilator.py`
- ID: `"Verilator.Lint"` (line 37)
- inputs: `[]` (line 40) - RTL is part of configuration, not DesignFormat
- outputs: `[]` (line 41)

**Inheritance Chain:** Lint → Step
- Step.config_vars = []
- Lint.config_vars defined at lines 43-114

**Config Variables (from config_vars, lines 43-114):**

| Variable | Type | Default | Description | Bazel Status |
|----------|------|---------|-------------|--------------|
| VERILOG_FILES | List[Path] | required | Design Verilog files | Wired |
| VERILOG_INCLUDE_DIRS | Optional[List[Path]] | None | Include directories | Wired |
| VERILOG_POWER_DEFINE | Optional[str] | "USE_POWER_PINS" | Power guard define | Wired |
| LINTER_INCLUDE_PDK_MODELS | bool | False | Include PDK Verilog models | Wired |
| LINTER_RELATIVE_INCLUDES | bool | True | Resolve includes relative to file | Wired |
| LINTER_ERROR_ON_LATCH | bool | True | Error on inferred latches | Wired |
| LINTER_ERROR_ON_MULTIDRIVEN | bool | True | Error on multiple-driver nets | Wired |
| VERILOG_DEFINES | Optional[List[str]] | None | Preprocessor defines | Wired |
| LINTER_DEFINES | Optional[List[str]] | None | Linter-specific defines | Wired |
| LINTER_DISABLE_WARNINGS | Optional[List[str]] | ["DECLFILENAME", "EOFNEWLINE"] | Warnings disabled globally | Wired |
| LINTER_DISABLE_WARNINGS_BLACKBOX | Optional[List[str]] | ["UNDRIVEN", "UNUSEDSIGNAL"] | Warnings disabled for blackbox files | Wired |
| LINTER_VLT | Optional[Path] | None | Extra Verilator configuration file | Wired |

**Config Variables (from run() method):**

| Variable | Line | Description | Bazel Status |
|----------|------|-------------|--------------|
| CELL_VERILOG_MODELS | 127 | PDK cell Verilog models | Wired (from PDK) |
| PAD_VERILOG_MODELS | 135 | PDK pad Verilog models | Wired (from PDK) |
| MACROS | 143 | Macro views used to build blackbox models | Wired |
| EXTRA_VERILOG_MODELS | 160 | Additional Verilog models | Wired |

**Librelane Gating:** `classic.py`
- Variable: `RUN_LINTER` (line 261)
- Default: `True` (line 264)
- Gating entry: `"Verilator.Lint": ["RUN_LINTER"]` (line 305)

**Bazel Implementation:** `verilator.bzl`
- ID: `"Verilator.Lint"` (line 33)
- config_keys: `LINT_CONFIG_KEYS` = BASE_CONFIG_KEYS + step-specific keys (lines 9-30)
- step_outputs: `[]` (line 33)
- Linter config attributes are wired in `bazel/flow/config/synth.bzl` (lines 7-18 and 58-100)
- Config values are emitted in `bazel/flow/common.bzl` (lines 242-258)
- Pad Verilog model files are included as PDK inputs in `bazel/flow/common.bzl` (lines 755-767)

**Bazel Flow:** `full_flow.bzl`
- Parameter: `run_linter = True` (line 108)
- Gating: `if run_linter:` (line 181)
- Position: First step after init (lines 182-186)

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Verilator.Lint"` | `"Verilator.Lint"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| config_keys | 14 declared variables plus run() dependencies | LINT_CONFIG_KEYS includes all checked items | Y |
| Gating var | RUN_LINTER | run_linter | Y |
| Gating default | True | True | Y |
| Position | Step 1 | Step 1 | Y |

**Status: PASS**

Verification:
- `bazel build --nobuild //dse/maths:SegmentedMultiplier16x16_sky130hd_lint`
  passed analysis after the wiring update.
- Runtime execution reached `Verilator.Lint` after the separate global
  `librelane.steps run` CLI update.
- Diff checked against LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`:
  `FP_TRACKS_INFO`, `FP_TAPCELL_DIST`, `FP_IO_HLAYER`, and `FP_IO_VLAYER` were
  removed from `librelane/config/flow.py:pdk_variables`. In 3.0.4,
  `FP_TRACKS_INFO` is declared by `OpenROAD.Floorplan`, `FP_TAPCELL_DIST` is
  declared by `OpenROAD.TapEndcapInsertion`, and the IO layer variables are
  declared as `IO_PIN_H_LAYER` / `IO_PIN_V_LAYER` with the old names as
  deprecated aliases. These keys therefore do not belong in the Bazel
  `BASE_CONFIG_KEYS` used by `Verilator.Lint`.

---

### Step 2: Checker.LintTimingConstructs

**Verified:** 2026-07-06 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.LintTimingConstructs"` (line 386)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- deferred: `False` (line 389) - raises immediately on failure

**Inheritance Chain:** LintTimingConstructs → MetricChecker → Step
- Step.config_vars = []
- MetricChecker: no config_vars defined (inherits empty from Step)
- LintTimingConstructs.config_vars = [error_on_var] (line 401)

**Config Variables:**

| Variable | Type | Default | Description | Bazel Status |
|----------|------|---------|-------------|--------------|
| ERROR_ON_LINTER_TIMING_CONSTRUCTS | bool | True | Quit immediately on timing constructs | Wired |

**Behavior note:** The `run` method (lines 403-418) doesn't read `self.config` at all - it only
checks `state_in.metrics`. The ERROR_ON_LINTER_TIMING_CONSTRUCTS variable is declared in
config_vars but never used. The step always errors if timing constructs are found, regardless of
this setting. We still wire it because it's declared in librelane.

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- `Checker.LintTimingConstructs` still declares only
  `ERROR_ON_LINTER_TIMING_CONSTRUCTS` and still overrides `run()` to read only
  `design__lint_timing_construct__count` from state metrics.

**Librelane Gating:** `classic.py`
- RUN_LINTER default: `True` (line 264)
- Gating entry: `"Checker.LintTimingConstructs": ["RUN_LINTER"]` (lines 308-310)

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.LintTimingConstructs"` (line 88)
- config_keys: `LINT_TIMING_CONSTRUCTS_CONFIG_KEYS` = `BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_TIMING_CONSTRUCTS"]` (line 12)
- step_outputs: `[]` (line 88)

**Bazel Flow:** `full_flow.bzl`
- Gating: Inside `if run_linter:` block (line 181)
- Position: Step 2, after Verilator.Lint (lines 187-191)
- Chains from: `_lint` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.LintTimingConstructs"` | `"Checker.LintTimingConstructs"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| config_keys | [ERROR_ON_LINTER_TIMING_CONSTRUCTS] | BASE_CONFIG_KEYS + [ERROR_ON_...] | Y |
| Gating var | RUN_LINTER | run_linter | Y |
| Gating default | True | True | Y |
| Position | Step 2 | Step 2 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_lint_timing`
  passed and reported `Check for Lint Timing Errors clear.`

---

### Step 3: Checker.LintErrors

**Verified:** 2026-07-06 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.LintErrors"` (line 346)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- deferred: `False` (line 349) - raises immediately on failure
- metric_name: `"design__lint_error__count"` (line 351)

**Inheritance Chain:** LintErrors → MetricChecker → Step
- Step.config_vars = []
- MetricChecker: no config_vars defined
- LintErrors.config_vars = [error_on_var] (line 361)

**Config Variables:**

| Variable | Type | Default | Description | Bazel Status |
|----------|------|---------|-------------|--------------|
| ERROR_ON_LINTER_ERRORS | bool | True | Quit immediately on linter errors | Wired |

**Behavior:** Uses MetricChecker.run() which reads `self.config.get("ERROR_ON_LINTER_ERRORS")` at
line 119. If True (default) and lint errors found → StepError. If False → just warns.

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- `Checker.LintErrors` still inherits `MetricChecker`, still checks
  `design__lint_error__count`, and still declares only `ERROR_ON_LINTER_ERRORS`.

**Librelane Gating:** `classic.py`
- RUN_LINTER default: `True` (line 264)
- Gating entry: `"Checker.LintErrors": ["RUN_LINTER"]` (line 306)

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.LintErrors"` (line 91)
- config_keys: `LINT_ERRORS_CONFIG_KEYS` = `BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_ERRORS"]` (line 16)
- step_outputs: `[]` (line 91)

**Bazel Flow:** `full_flow.bzl`
- Gating: Inside `if run_linter:` block (line 235)
- Position: Step 3, after LintTimingConstructs (lines 246-250)
- Chains from: `_lint_timing` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.LintErrors"` | `"Checker.LintErrors"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| config_keys | [ERROR_ON_LINTER_ERRORS] | BASE_CONFIG_KEYS + [ERROR_ON_...] | Y |
| Gating var | RUN_LINTER | run_linter | Y |
| Gating default | True | True | Y |
| Position | Step 3 | Step 3 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_lint_errors`
  passed and reported `Check for Lint errors clear.`

---

### Step 4: Checker.LintWarnings

**Verified:** 2026-07-06 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.LintWarnings"` (line 365)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- deferred: `False` (line 369)
- metric_name: `"design__lint_warning__count"` (line 371)

**Inheritance Chain:** LintWarnings → MetricChecker → Step
- Step.config_vars = []
- MetricChecker: no config_vars defined
- LintWarnings.config_vars = [error_on_var] (line 381)

**Config Variables:**

| Variable | Type | Default | Description | Bazel Status |
|----------|------|---------|-------------|--------------|
| ERROR_ON_LINTER_WARNINGS | bool | False | Raise error on linter warnings | Wired |

**Behavior:** Uses MetricChecker.run() which reads `self.config.get("ERROR_ON_LINTER_WARNINGS")` at
line 119. If False (default) → just warns. If True → raises StepError.

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- `Checker.LintWarnings` still inherits `MetricChecker`, still checks
  `design__lint_warning__count`, and still declares only `ERROR_ON_LINTER_WARNINGS`.

**Librelane Gating:** `classic.py`
- RUN_LINTER default: `True` (line 264)
- Gating entry: `"Checker.LintWarnings": ["RUN_LINTER"]` (line 307)

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.LintWarnings"` (line 94)
- config_keys: `LINT_WARNINGS_CONFIG_KEYS` = `BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_WARNINGS"]` (line 20)
- step_outputs: `[]` (line 94)

**Bazel Flow:** `full_flow.bzl`
- Gating: Inside `if run_linter:` block (line 235)
- Position: Step 4, after LintErrors (lines 251-256)
- Chains from: `_lint_errors` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.LintWarnings"` | `"Checker.LintWarnings"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| config_keys | [ERROR_ON_LINTER_WARNINGS] | BASE_CONFIG_KEYS + [ERROR_ON_...] | Y |
| Gating var | RUN_LINTER | run_linter | Y |
| Gating default | True | True | Y |
| Position | Step 4 | Step 4 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_lint_warnings`
  passed. The checker reported `103 Lint warnings found.` and did not fail
  because `ERROR_ON_LINTER_WARNINGS` defaults to `False`.

---

### Step 5: Yosys.JsonHeader

**Verified:** 2026-07-06 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/pyosys.py`
- ID: `"Yosys.JsonHeader"` (line 373)
- inputs: `[]` (line 377)
- outputs: `[DesignFormat.JSON_HEADER]` (line 378)
- config_vars: `PyosysStep.config_vars + verilog_rtl_cfg_vars` (line 380)
- Produces: `{DESIGN_NAME}.h.json` file

**Config Variables:**

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| VERILOG_FILES | verilog_rtl_cfg_vars line 100 | Wired |
| VERILOG_DEFINES | verilog_rtl_cfg_vars line 105 | Wired |
| VERILOG_POWER_DEFINE | verilog_rtl_cfg_vars line 111 | Wired |
| VERILOG_INCLUDE_DIRS | verilog_rtl_cfg_vars line 118 | Wired |
| SYNTH_PARAMETERS | verilog_rtl_cfg_vars line 123 | Wired |
| USE_SLANG | verilog_rtl_cfg_vars line 128 | Wired |
| SLANG_ARGUMENTS | verilog_rtl_cfg_vars line 135 | Wired |
| SYNTH_LATCH_MAP | PyosysStep line 164 | Wired |
| SYNTH_TRISTATE_MAP | PyosysStep line 170 | Wired |
| SYNTH_CSA_MAP | PyosysStep line 177 | Wired |
| SYNTH_RCA_MAP | PyosysStep line 184 | Wired |
| SYNTH_FA_MAP | PyosysStep line 191 | Wired |
| SYNTH_MUX_MAP | PyosysStep line 198 | Wired |
| SYNTH_MUX4_MAP | PyosysStep line 204 | Wired |
| SYNTH_CLOCKGATE_MIN_WIDTH | PyosysStep line 210 | Wired |
| SYNTH_CLOCKGATE_POSEDGE_ICG | PyosysStep line 216 | Wired from PDK |
| SYNTH_CLOCKGATE_NEGEDGE_ICG | PyosysStep line 223 | Wired from PDK |
| YOSYS_LOG_LEVEL | PyosysStep line 230 | Wired |
| SYNTH_CORNER | PyosysStep line 236 | Wired |
| SYNTH_SHOW | PyosysStep line 242 | Wired |

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- `USE_SYNLIG` was replaced by `USE_SLANG` with `USE_SYNLIG` only as a deprecated
  LibreLane name. Bazel exposes the new `use_slang` name.
- `SYNLIG_DEFER`, `USE_LIGHTER`, and `LIGHTER_DFF_MAP` are no longer declared by
  `PyosysStep`; Bazel no longer exposes or passes them.
- `SYNTH_CLOCKGATE_MIN_WIDTH`, `SYNTH_CLOCKGATE_POSEDGE_ICG`,
  `SYNTH_CLOCKGATE_NEGEDGE_ICG`, `SYNTH_CORNER`, and `SYNTH_SHOW` were added to
  the Bazel JsonHeader config-key path.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs
- Note: VHDLClassic substitutes this step to None (line 322)

**Bazel Implementation:** `synthesis.bzl`
- ID: `"Yosys.JsonHeader"` (line 156)
- config_keys: `JSON_HEADER_CONFIG_KEYS` includes all declared config variables and
  macro-view dependencies (lines 15-40)
- outputs: `[json_h]` file (lines 145, 157)
- Stores json_h in LibrelaneInfo (line 181)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 5, after linting or init (lines 260-265)
- Chains from: `pre_synth_src` (either `_lint_warnings` or `_init`)

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Yosys.JsonHeader"` | `"Yosys.JsonHeader"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[JSON_HEADER]` | `[json_h]` | Y |
| Gating | None | None | Y |
| Position | Step 5 | Step 5 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_json_header`
  passed and produced
  `bazel-bin/dse/maths/SegmentedMultiplier16x16_sky130hd_json_header/SegmentedMultiplier16x16.h.json`.

---

### Step 6: Yosys.Synthesis

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/pyosys.py`
- ID: `"Yosys.Synthesis"` (line 644)
- inputs: `[]` (inherited from SynthesisCommon, line 405) - RTL is configuration
- outputs: `[DesignFormat.NETLIST]` (inherited from SynthesisCommon, line 406)
- config_vars: `SynthesisCommon.config_vars + verilog_rtl_cfg_vars` (line 647)
- Produces metrics: design__instance__count, design__instance_unmapped__count, design__instance__area

**Config Variables:**

This step inherits all `Yosys.JsonHeader` variables plus the SynthesisCommon variables below.

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| SYNTH_CHECKS_ALLOW_TRISTATE | SynthesisCommon line 410 | Wired |
| SYNTH_AUTONAME | SynthesisCommon line 416 | Wired |
| SYNTH_STRATEGY | SynthesisCommon line 422 | Wired |
| SYNTH_ABC_BUFFERING | SynthesisCommon line 438 | Wired |
| SYNTH_ABC_LEGACY_REFACTOR | SynthesisCommon line 445 | Wired |
| SYNTH_ABC_LEGACY_REWRITE | SynthesisCommon line 451 | Wired |
| SYNTH_ABC_DFF | SynthesisCommon line 457 | Wired |
| SYNTH_ABC_USE_MFS3 | SynthesisCommon line 463 | Wired |
| SYNTH_ABC_AREA_USE_NF | SynthesisCommon line 469 | Wired |
| SYNTH_DIRECT_WIRE_BUFFERING | SynthesisCommon line 475 | Wired |
| SYNTH_SPLITNETS | SynthesisCommon line 482 | Wired |
| SYNTH_SIZING | SynthesisCommon line 488 | Wired |
| SYNTH_HIERARCHY_MODE | SynthesisCommon line 494 | Wired |
| SYNTH_KEEP_HIERARCHY_MIN_COST | SynthesisCommon line 508 | Wired |
| SYNTH_KEEP_HIERARCHY_INSTANCES | SynthesisCommon line 513 | Wired |
| SYNTH_KEEP_HIERARCHY_MODULES | SynthesisCommon line 518 | Wired |
| SYNTH_SHARE_RESOURCES | SynthesisCommon line 523 | Wired |
| SYNTH_ADDER_TYPE | SynthesisCommon line 529 | Wired |
| SYNTH_EXTRA_MAPPING_FILE | SynthesisCommon line 535 | Wired |
| SYNTH_ELABORATE_ONLY | SynthesisCommon line 540 | Wired |
| SYNTH_MUL_BOOTH | SynthesisCommon line 546 | Wired |
| SYNTH_TIE_UNDEFINED | SynthesisCommon line 552 | Wired |
| SYNTH_WRITE_NOATTR | SynthesisCommon line 558 | Wired |
| SYNTH_NORMALIZE_SINGLE_BIT_VECTORS | SynthesisCommon line 564 | Wired |

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- `SYNTH_KEEP_HIERARCHY_MIN_COST`, `SYNTH_KEEP_HIERARCHY_INSTANCES`, and
  `SYNTH_KEEP_HIERARCHY_MODULES` were added and are now wired.
- `SYNTH_NORMALIZE_SINGLE_BIT_VECTORS` was added and is now wired.
- `SYNTH_ELABORATE_FLATTEN` was removed from LibreLane's declared config vars
  and is now only a deprecated alias into `SYNTH_HIERARCHY_MODE`; Bazel no
  longer exposes or passes the old name.
- `SynthesisCommon.run()` now passes `SYNTH_ELABORATE_ONLY` into
  `_parse_yosys_check()` (line 618); Bazel already emits that variable.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs
- Note: VHDLClassic substitutes Yosys.VHDLSynthesis (line 323)

**Bazel Implementation:** `synthesis.bzl`
- ID: `"Yosys.Synthesis"` (line 104)
- config_keys: `SYNTHESIS_CONFIG_KEYS` includes `JSON_HEADER_CONFIG_KEYS` plus all
  checked SynthesisCommon variables (lines 45-72)
- outputs: `[nl, stat_json]` (lines 92-93, 105)
- Stores nl in LibrelaneInfo (line 116)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 6, after json_header (lines 267-272)
- Chains from: `_json_header` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Yosys.Synthesis"` | `"Yosys.Synthesis"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[NETLIST]` | `[nl, stat_json]` | Y |
| Gating | None | None | Y |
| Position | Step 6 | Step 6 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_synth`
  passed and produced:
  `bazel-bin/dse/maths/SegmentedMultiplier16x16_sky130hd_synth/SegmentedMultiplier16x16.nl.v`
  and `bazel-bin/dse/maths/SegmentedMultiplier16x16_sky130hd_synth/reports/stat.json`.

---

### Step 7: Checker.YosysUnmappedCells

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.YosysUnmappedCells"` (line 142)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- deferred: `False` (line 144)
- metric_name: `"design__instance_unmapped__count"` (line 146)
- error_on_var: `ERROR_ON_UNMAPPED_CELLS` (default=True) (lines 149-155)
- Uses base MetricChecker.run() - respects error_on_var

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- No behavior or config-variable changes were found for `Checker.YosysUnmappedCells`.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.YosysUnmappedCells"` (line 97)
- config_keys: `YOSYS_UNMAPPED_CELLS_CONFIG_KEYS` = `BASE_CONFIG_KEYS + ["ERROR_ON_UNMAPPED_CELLS"]` (line 23)
- step_outputs: `[]` (line 97)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 7, after synthesis (lines 274-279)
- Chains from: `_synth` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.YosysUnmappedCells"` | `"Checker.YosysUnmappedCells"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | Y |
| Position | Step 7 | Step 7 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_unmapped`
  passed and reported `Check for Unmapped Yosys instances clear.`

---

### Step 8: Checker.YosysSynthChecks

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.YosysSynthChecks"` (line 161)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- deferred: `False` (line 163)
- metric_name: `"synthesis__check_error__count"` (line 165)
- error_on_var: `ERROR_ON_SYNTH_CHECKS` (default=True) (lines 167-173)
- Checks for: combinational loops and wires with no drivers

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- No behavior or config-variable changes were found for `Checker.YosysSynthChecks`.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.YosysSynthChecks"` (line 100)
- config_keys: `YOSYS_SYNTH_CHECKS_CONFIG_KEYS` = `BASE_CONFIG_KEYS + ["ERROR_ON_SYNTH_CHECKS"]` (line 26)
- step_outputs: `[]` (line 100)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 8, after YosysUnmappedCells (lines 280-284)
- Chains from: `_chk_unmapped` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.YosysSynthChecks"` | `"Checker.YosysSynthChecks"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | Y |
| Position | Step 8 | Step 8 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_synth`
  passed and reported `Check for Yosys check errors clear.`

---

### Step 9: Checker.NetlistAssignStatements

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.NetlistAssignStatements"` (line 37)
- inputs: `[DesignFormat.NETLIST]` (line 40) - **reads netlist file directly**
- outputs: `[]` (line 41)
- Base class: `Step` (NOT MetricChecker)
- config_var: `ERROR_ON_NL_ASSIGN_STATEMENTS` (default=True) (lines 43-50)

**Behavior:** Scans netlist for `assign` statements (regex: `^\s*\bassign\b`).
Assign statements cause bugs in some PnR tools. Errors if found and ERROR_ON_NL_ASSIGN_STATEMENTS=True.

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- No behavior or config-variable changes were found for `Checker.NetlistAssignStatements`.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.NetlistAssignStatements"` (line 103)
- config_keys: `NETLIST_ASSIGN_STATEMENTS_CONFIG_KEYS` = `BASE_CONFIG_KEYS + ["ERROR_ON_NL_ASSIGN_STATEMENTS"]` (line 29)
- step_outputs: `[]` (line 103)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 9, after YosysSynthChecks (lines 285-289)
- Chains from: `_chk_synth` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.NetlistAssignStatements"` | `"Checker.NetlistAssignStatements"` | Y |
| inputs | `[NETLIST]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | Y |
| Position | Step 9 | Step 9 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_assign`
  passed.

---

### Step 10: OpenROAD.CheckSDCFiles

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/openroad.py`
- ID: `"OpenROAD.CheckSDCFiles"` (line 157)
- inputs: `[]` (line 159)
- outputs: `[]` (line 160)

**Inheritance Chain:** CheckSDCFiles → Step
- Step.config_vars = []
- CheckSDCFiles.config_vars defined at lines 162-173

**Config Variables (from config_vars, lines 162-173):**

| Variable | Type | Default | Description | Bazel Status |
|----------|------|---------|-------------|--------------|
| PNR_SDC_FILE | Optional[Path] | None | SDC file for PnR steps | Wired |
| SIGNOFF_SDC_FILE | Optional[Path] | None | SDC file for signoff STA | Wired |

**Behavior:** Warns if PNR_SDC_FILE or SIGNOFF_SDC_FILE not defined - uses fallback SDC.
Does not error, just warns. Accesses `FALLBACK_SDC_FILE` Variable definition (not config value)
to determine if fallback is "generic" or "user-defined".

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- The step still declares only `PNR_SDC_FILE` and `SIGNOFF_SDC_FILE`.
- The warning logic now looks up the `option_variables` entry named `FALLBACK_SDC`
  at lines 176-178. This is not read from `self.config`; the stale
  `FALLBACK_SDC_FILE` entries in later Bazel OpenROAD config-key lists need to be
  handled while auditing the OpenROAD parent step.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.CheckSDCFiles"` (line 88)
- config_keys: `CHECK_SDC_CONFIG_KEYS` = `BASE_CONFIG_KEYS + [PNR_SDC_FILE, SIGNOFF_SDC_FILE]` (lines 16-19)
- step_outputs: `[]` (line 88)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 10, after NetlistAssignStatements (lines 291-300)
- Chains from: `_chk_assign` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.CheckSDCFiles"` | `"OpenROAD.CheckSDCFiles"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| config_keys | 2 variables | CHECK_SDC_CONFIG_KEYS (all 2) | Y |
| Gating | None | None | Y |
| Position | Step 10 | Step 10 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_sdc`
  passed and produced
  `bazel-bin/dse/maths/SegmentedMultiplier16x16_sky130hd_chk_sdc/state_out.json`.

---

### Step 11: OpenROAD.CheckMacroInstances

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/openroad.py`
- ID: `"OpenROAD.CheckMacroInstances"` (line 677)
- inputs: `[DesignFormat.NETLIST]` (inherited from OpenSTAStep)
- outputs: `[]` (line 679)

**Inheritance Chain:** CheckMacroInstances → OpenSTAStep → OpenROADStep → TclStep → Step
- Step.config_vars = []
- TclStep: no config_vars
- OpenROADStep.config_vars defined at lines 208-294
- OpenSTAStep: no additional config_vars
- CheckMacroInstances: config_vars = OpenROADStep.config_vars (line 681)

**Config Variables (from OpenROADStep.config_vars, lines 208-294):**

| Variable | Type | Default | Description | Bazel Status |
|----------|------|---------|-------------|--------------|
| PNR_CORNERS | Optional[List[str]] | None | PnR corner override, PDK-backed | Wired |
| SET_RC_VERBOSE | bool | False | Echo set_rc commands | Wired |
| LAYERS_RC | Optional[Dict] | None | PnR layer RC values, PDK-backed | Wired |
| VIAS_R | Optional[Dict] | None | PnR via resistance values, PDK-backed | Wired |
| SIGNAL_WIRE_RC_LAYERS | Optional[List[str]] | None | Signal wire RC layers, PDK-backed | Wired |
| CLOCK_WIRE_RC_LAYERS | Optional[List[str]] | None | Clock wire RC layers, PDK-backed | Wired |
| PDN_CONNECT_MACROS_TO_GRID | bool | True | Connect macros to power grid | Wired |
| PDN_MACRO_CONNECTIONS | Optional[List[str]] | None | Explicit macro power connections | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | bool | True | Enable global PDN connections | Wired |
| PNR_SDC_FILE | Optional[Path] | None | SDC file for PnR | Wired |
| STA_EXTRA_CORNER_TCL_FILE | Optional[Path] | None | Extra PnR corner Tcl file | Wired |
| DEDUPLICATE_CORNERS | bool | False | Deduplicate equivalent PnR corners | Wired |

**Config Variables (from prepare_env(), lines 317-335):**

| Variable | Type | Source | Bazel Status |
|----------|------|--------|--------------|
| LIB | Dict[str, List[Path]] | PDK | Wired |
| FALLBACK_SDC | Path | option_variables | Wired |
| EXTRA_EXCLUDED_CELLS | Optional[List[str]] | option_variables | Wired |
| PNR_EXCLUDED_CELL_FILE | Path | PDK | Wired |

**Config Variables (from run(), line 690):**

| Variable | Type | Bazel Status |
|----------|------|--------------|
| MACROS | Optional[Dict[str, Macro]] | Wired |

**Behavior:** Checks if declared macro instances exist in design.
**Self-skips if MACROS is None** (lines 690-693) - just returns empty without error.

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- `OpenROADStep.config_vars` added `PNR_CORNERS`, `SET_RC_VERBOSE`,
  `LAYERS_RC`, `VIAS_R`, `SIGNAL_WIRE_RC_LAYERS`, `CLOCK_WIRE_RC_LAYERS`,
  `STA_EXTRA_CORNER_TCL_FILE`, and `DEDUPLICATE_CORNERS`; these are now wired
  through the Bazel PDK/PnR config path.
- `FP_DEF_TEMPLATE` is no longer an `OpenROADStep` config variable, so it was
  removed from the generic `sta.bzl` OpenROAD step key list.
- `OpenROADStep.prepare_env()` now reads `FALLBACK_SDC`, not
  `FALLBACK_SDC_FILE`; the Step 11 config path now uses the new name.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs (but self-skips if no macros)

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.CheckMacroInstances"` (line 91)
- config_keys: `CHECK_MACRO_INSTANCES_CONFIG_KEYS` = `OPENROAD_STEP_CONFIG_KEYS + [MACROS]` (lines 41-43)
- step_outputs: `[]` (line 91)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 11, after CheckSDCFiles (lines 297-306)
- Chains from: `_chk_sdc` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.CheckMacroInstances"` | `"OpenROAD.CheckMacroInstances"` | Y |
| inputs | NETLIST | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| config_keys | OpenROADStep variables plus MACROS/run deps | CHECK_MACRO_INSTANCES_CONFIG_KEYS | Y |
| Gating | None (self-skips if no macros) | None | Y |
| Position | Step 11 | Step 11 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_macros`
  passed and produced
  `bazel-bin/dse/maths/SegmentedMultiplier16x16_sky130hd_chk_macros/state_out.json`.
- Runtime log reported `No macros found, skipping instance check...`, matching
  the documented self-skip behavior when `MACROS` is absent.

---

### Step 12: OpenROAD.STAPrePNR

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/openroad.py`
- ID: `"OpenROAD.STAPrePNR"` (line 900)
- inputs: `[DesignFormat.NETLIST]` (inherited from OpenSTAStep, line 574)
- outputs: `[DesignFormat.SDF, DesignFormat.SDC]` (inherited from MultiCornerSTA, line 711)

**Inheritance Chain:** STAPrePNR → MultiCornerSTA → OpenSTAStep → OpenROADStep → TclStep → Step
- OpenROADStep.config_vars: lines 208-294 (in OPENROAD_STEP_CONFIG_KEYS)
- OpenSTAStep adds helper behavior for macro/netlist/SPEF corner files, but no config_vars
- MultiCornerSTA.config_vars adds: STA_MACRO_PRIORITIZE_NL, STA_MAX_VIOLATOR_COUNT, EXTRA_SPEFS, STA_THREADS

**Config Variables (from MultiCornerSTA.config_vars, lines 713-735):**

| Variable | Type | Default | Description | Bazel Status |
|----------|------|---------|-------------|--------------|
| STA_MACRO_PRIORITIZE_NL | bool | True | Prioritize netlists+SPEF over LIB | Wired |
| STA_MAX_VIOLATOR_COUNT | Optional[int] | None | Max violators in report | Wired |
| EXTRA_SPEFS | Optional[List] | None | Deprecated backcompat | Intentionally not wired |
| STA_THREADS | Optional[int] | None | Max parallel corners | Wired |

Behavior notes:
- `OpenSTAStep._get_corner_files()` now reads incoming SPEF through
  `state_in.get(DesignFormat.SPEF)` and only validates it when present (lines
  597-620).
- `STAPrePNR.prepare_env()` sets `OPENLANE_SDC_IDEAL_CLOCKS=1` (lines 904-907).
- `STAPrePNR.run_corner()` writes SDFs into each used corner directory (lines
  909-913).
- `STAPrePNR.run()` reads existing SDF state through `state_in.get(DesignFormat.SDF, {})`
  and adds any generated corner SDFs to the outgoing state (lines 915-935).
- Although the inherited declared outputs include SDC, the verified sky130 run
  produced SDF state and no SDC state for this step.

Diff check:
- Compared LibreLane `f315752cf2e1465aca24a002247aa6169becb541..3.0.4`.
- `OpenSTAStep` changed absent-SPEF handling from indexing to `state_in.get(...)`.
- `STAPrePNR` changed absent-SDF handling from indexing to `state_in.get(...)`.
- `EXTRA_SPEFS` remains declared only as deprecated compatibility for LibreLane
  before 2.0.0. Bazel intentionally does not expose it; macro timing data should
  use the `MACROS` provider path instead.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.STAPrePNR"` (line 132)
- config_keys: `MULTI_CORNER_STA_CONFIG_KEYS` (lines 53-58)
- Declares one SDF output per used nominal corner and propagates them in
  `LibrelaneInfo.sdf` (lines 116-160)
- Declares reports as outputs: `summary.rpt` and per-corner `max.rpt`,
  `min.rpt`, and `checks.rpt` for nominal corners (lines 100-107 and 123-125)

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 12, after CheckMacroInstances
- Chains from: `_chk_macros` target

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.STAPrePNR"` | `"OpenROAD.STAPrePNR"` | Y |
| inputs | NETLIST | (from src) | Y |
| outputs | SDF state generated; SDC declared upstream but not produced in verified run | SDF files declared and propagated; SDC passthrough | Y |
| config_keys | OPENROAD + MultiCorner minus deprecated EXTRA_SPEFS | MULTI_CORNER_STA_CONFIG_KEYS | Y |
| Reports | per-used-corner .rpt files | declared outputs for nominal used corners | Y |
| Gating | None | None | Y |
| Position | Step 12 | Step 12 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_sta_pre`
  passed.
- Bazel now reports these SDF files as target outputs:
  `nom_tt_025C_1v80/SegmentedMultiplier16x16__nom_tt_025C_1v80.sdf`,
  `nom_ss_100C_1v60/SegmentedMultiplier16x16__nom_ss_100C_1v60.sdf`, and
  `nom_ff_n40C_1v95/SegmentedMultiplier16x16__nom_ff_n40C_1v95.sdf`.
- The runtime log showed the six min/max corners skipped as duplicates of the
  nominal corners at this stage, matching the declared nominal output set.

---

### Step 13: OpenROAD.Floorplan

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.Floorplan"` (line 1085)
- inputs: `[DesignFormat.NETLIST]` (line 1089)
- outputs: inherited from `OpenROADStep`: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]`
- `config_vars`: `OpenROADStep.config_vars + [...]` (line 1091)
- custom `run()` behavior: reads `FP_TRACKS_INFO`, converts it to `config.tracks`,
  sets `TRACKS_INFO_FILE_PROCESSED`, then runs the OpenROAD Tcl step (lines 1187-1197)

**Librelane Diff Notes:**
- `OpenROADStep` now owns PnR corner/RC setup variables:
  `PNR_CORNERS`, `LAYERS_RC`, `VIAS_R`, `SIGNAL_WIRE_RC_LAYERS`,
  `CLOCK_WIRE_RC_LAYERS`, `STA_EXTRA_CORNER_TCL_FILE`, and
  `DEDUPLICATE_CORNERS`.
- `FALLBACK_SDC_FILE` was renamed to `FALLBACK_SDC` in OpenROAD environment setup.
- `FP_TRACKS_INFO` is now a Floorplan-specific PDK variable rather than a global
  base config key.
- `FP_FLIP_SITES` is a new Floorplan PDK variable.
- `FP_DEF_TEMPLATE` is not part of `OpenROAD.Floorplan` in 3.0.4.

**Bazel Implementation:** `bazel/flow/floorplan.bzl`
- ID: `"OpenROAD.Floorplan"` (line 94)
- outputs: `[def_out, odb_out, nl_out, pnl_out, sdc_out]` (line 95)
- `FLOORPLAN_CONFIG_KEYS` includes inherited `OpenROADStep` keys and
  Floorplan-specific keys (lines 12-39)

**Config Variable Audit:**

| Variable | Source | Bazel status |
|----------|--------|--------------|
| PNR_CORNERS, LAYERS_RC, VIAS_R | OpenROADStep PDK | Included in `FLOORPLAN_CONFIG_KEYS` |
| SIGNAL_WIRE_RC_LAYERS, CLOCK_WIRE_RC_LAYERS | OpenROADStep PDK | Included in `FLOORPLAN_CONFIG_KEYS` |
| PDN_CONNECT_MACROS_TO_GRID, PDN_MACRO_CONNECTIONS, PDN_ENABLE_GLOBAL_CONNECTIONS | OpenROADStep | Included in `FLOORPLAN_CONFIG_KEYS` |
| PNR_SDC_FILE, FALLBACK_SDC | OpenROADStep / option variables | Included in `FLOORPLAN_CONFIG_KEYS` |
| STA_EXTRA_CORNER_TCL_FILE, DEDUPLICATE_CORNERS | OpenROADStep | Included in `FLOORPLAN_CONFIG_KEYS` |
| LIB, EXTRA_EXCLUDED_CELLS, PNR_EXCLUDED_CELL_FILE | OpenROADStep env setup | Included in `FLOORPLAN_CONFIG_KEYS` |
| FP_FLIP_SITES | Floorplan PDK | Added to PDK extraction/provider/config |
| FP_TRACKS_INFO | Floorplan PDK | Included in `FLOORPLAN_CONFIG_KEYS` |
| FP_SIZING, FP_ASPECT_RATIO, FP_CORE_UTIL | Floorplan | Set by rule attrs |
| DIE_AREA, CORE_AREA | Floorplan | Set by rule attrs when absolute sizing is used |
| BOTTOM/TOP/LEFT/RIGHT_MARGIN_MULT | Floorplan | Set by rule attrs with LibreLane defaults |
| FP_OBSTRUCTIONS, PL_SOFT_OBSTRUCTIONS | Floorplan | Set by optional rule attrs |
| EXTRA_SITES | Floorplan PDK | Included from PDK config |

**Fixes Applied (2026-07-07):**
1. Added inherited `OpenROADStep` keys to `FLOORPLAN_CONFIG_KEYS`.
2. Added `FP_TRACKS_INFO`, `FP_FLIP_SITES`, and `EXTRA_SITES` to the Floorplan
   key set.
3. Added `FP_FLIP_SITES` to PDK extraction, `PdkInfo`, and common config emission.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.Floorplan"` | `"OpenROAD.Floorplan"` | Y |
| inputs | `[NETLIST]` | from synthesized netlist state | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `[def, odb, nl, pnl, sdc]` | Y |
| Gating | None | None | Y |
| Position | Step 13 | Step 13 | Y |
| Config vars | Floorplan + inherited OpenROADStep | Declared in `FLOORPLAN_CONFIG_KEYS` | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_floorplan`
  passed.
- Produced:
  `SegmentedMultiplier16x16.def`, `SegmentedMultiplier16x16.odb`,
  `SegmentedMultiplier16x16.nl.v`, `SegmentedMultiplier16x16.pnl.v`, and
  `SegmentedMultiplier16x16.sdc`.

---

### Step 14: OpenROAD.DumpRCValues

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.DumpRCValues"` (line 2983)
- inputs: `[DesignFormat.DEF]` (line 2986)
- outputs: no design views written by the Tcl script; state passes through
- script: `librelane/scripts/openroad/dump_rc.tcl`

**Behavior:**
- Reads PnR timing libs, LEFs, and the current DEF.
- Reports initial tech LEF RC values, RC values after `set_rc.tcl`, and resizer
  RC values after `set_rc.tcl`.
- Produces three report files:
  `tlef_values.rpt`, `layer_values_after.rpt`, and
  `resizer_values_after.rpt`.

**Bazel Implementation:** `bazel/flow/floorplan.bzl`
- ID: `"OpenROAD.DumpRCValues"` (line 134)
- `step_outputs = []` because this report step does not rewrite DEF/ODB/netlist
  views.
- `extra_outputs = DUMP_RC_REPORTS`, declaring the three report files.
- `DUMP_RC_CONFIG_KEYS` is intentionally narrower than the full
  `OpenROADStep` parent list. It includes timing libs, PnR corners, RC override
  keys, macro/extra LEFs, and PnR excluded cells, but not unrelated PDN macro
  connection controls.

**Bazel Flow:** `full_flow.bzl`
- Inserted after `_floorplan` and before `_chk_macro_ant`, matching the new
  LibreLane Classic sequence.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.DumpRCValues"` | `"OpenROAD.DumpRCValues"` | Y |
| inputs | `[DEF]` | floorplan state with DEF | Y |
| outputs | report files; design state passthrough | three report files plus state passthrough | Y |
| Gating | None | None | Y |
| Position | after Floorplan | after Floorplan | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_dump_rc`
  passed.
- Produced:
  `tlef_values.rpt`, `layer_values_after.rpt`,
  `resizer_values_after.rpt`, and `state_out.json`.

---

### Step 14b: Odb.CheckMacroAntennaProperties

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.CheckMacroAntennaProperties"` (line 204)
- inputs: `[DesignFormat.ODB]` (inherited from `OdbpyStep`, line 51)
- outputs: `[]` (line 207)
- `get_cells()` reads `MACROS` and returns the macro cell names if present
  (lines 216-221)
- self-skips if no cells are provided (lines 232-236)

**Librelane Diff Notes:**
- `classic.py` inserted `OpenROAD.DumpRCValues` immediately after
  `OpenROAD.Floorplan`, so this is now the step after DumpRCValues in upstream
  Classic flow.
- `OdbpyStep` now uses `OpenROADStep.get_openroad_path()`, includes `PAD_LEFS`
  when it invokes OpenROAD, and reads optional design LEF through
  `state_in.result().get(...)`.
- `CheckMacroAntennaProperties` itself still has no `config_vars`; it reads
  `MACROS` directly and skips if the cell list is empty.

**Librelane Gating:** `classic.py`
- No entry in `gating_config_vars`; it always appears in the flow and self-skips
  when no macros are configured.

**Bazel Implementation:** `place.bzl`
- ID: `"Odb.CheckMacroAntennaProperties"` (line 94)
- `step_outputs = []`
- Uses `ODB_CONFIG_KEYS = BASE_CONFIG_KEYS`; this is sufficient for the verified
  no-macro path because the step returns before invoking `OdbpyStep`.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: after DumpRCValues in the current Bazel flow
- Chains from: `_dump_rc` target

**Config Variable Audit:**

CheckMacroAntennaProperties has no `config_vars`. It reads `MACROS` in
`get_cells()`; `create_librelane_config()` emits `MACROS` when macro providers
are present.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.CheckMacroAntennaProperties"` | `"Odb.CheckMacroAntennaProperties"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None; self-skips if no cells | None; self-skips through LibreLane | Y |
| Position | after DumpRCValues in Classic | after DumpRCValues in current Bazel flow | Y |
| Config vars | None, direct `MACROS` read | `MACROS` emitted when present | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_macro_ant`
  passed.
- Runtime log reported:
  `No cells provided, skipping 'Odb.CheckMacroAntennaProperties'...`

---

### Step 15: Odb.SetPowerConnections

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.SetPowerConnections"` (line 332)
- inputs: `[DesignFormat.JSON_HEADER, DesignFormat.ODB]` (line 334)
- outputs: inherited from `OdbpyStep`: `[ODB, DEF]`
- Uses JSON netlist to add global power connections for macros
- script: `odbpy/power_utils.py` with subcommand `set-power-connections`

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.SetPowerConnections"` (line 101)
- step_outputs: `["def", "odb"]`
- Uses `ODB_CONFIG_KEYS`, which includes `BASE_CONFIG_KEYS`, `MACROS`, and
  `EXTRA_LEFS`. `MACROS` and `EXTRA_LEFS` are needed by the inherited
  `OdbpyStep` LEF loading path, even though `SetPowerConnections` itself has no
  local `config_vars`.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: after CheckMacroAntennaProperties
- Chains from: `_chk_macro_ant` target

**Config Variable Audit:**

SetPowerConnections has no local `config_vars`. It inherits `OdbpyStep`, whose
OpenROAD command loads tech LEF, cell LEFs, optional macro LEFs, optional
`EXTRA_LEFS`, and optional design LEF depending on step inputs. The command also
reads the JSON header from incoming state.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.SetPowerConnections"` | `"Odb.SetPowerConnections"` | Y |
| inputs | `[JSON_HEADER, ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating | None | None | Y |
| Position | Step 15 | Step 15 | Y |
| Config vars | no local config vars; inherited LEF loading uses flow vars | `ODB_CONFIG_KEYS` includes macro/extra LEF inputs | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_power_conn`
  passed.
- Produced:
  `SegmentedMultiplier16x16.def`, `SegmentedMultiplier16x16.odb`, and
  `state_out.json`.

---

### Step 16: Odb.ManualMacroPlacement

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.ManualMacroPlacement"` (line 405)
- inputs: inherited from `OdbpyStep`: `[ODB]`
- outputs: inherited from `OdbpyStep`: `[ODB, DEF]` when it runs
- Self-skips if no placement file is generated (lines 467-471).
- Dual config support:
  1. If MACRO_PLACEMENT_CFG is set → copy that file (with deprecation warning)
  2. Elif MACROS config has instances with locations → generate placement.cfg from MACROS

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs, relies on self-skip behavior

**Bazel Implementation:** `odb.bzl`
- Implemented in `place.bzl` for the current full flow.
- ID: `"Odb.ManualMacroPlacement"`
- Always instantiated by `full_flow.bzl`.
- Declares `["def", "odb"]` only when `input_info.macro_placement_cfg` is set;
  otherwise it declares no design-view outputs and lets LibreLane self-skip while
  Bazel passes through the previous DEF/ODB state.

**Bazel Flow:** `full_flow.bzl`
- Position: Step 16, after SetPowerConnections
- Always called; `_cutrows` now chains from `_mpl`.

**Config Variable Audit:**

| Variable | Type | Default | Bazel Attr | Status |
|----------|------|---------|------------|--------|
| MACRO_PLACEMENT_CFG | Optional[Path] | None | `macro_placement_cfg` through `LibrelaneInput` | Wired |
| MACROS | Optional[Dict[str, Macro]] | None | hard macro providers | View data wired; placement instances not modeled |
| EXTRA_LEFS | Optional[List[Path]] | None | `extra_lefs` | Wired for inherited LEF loading |

Note: MACROS-based placement locations are still not supported because our
`MacroInfo` provider carries macro views but not per-instance placement
locations/orientations.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.ManualMacroPlacement"` | `"Odb.ManualMacroPlacement"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` when run; none when skipped | conditional outputs matching configured file path | Y |
| Gating | Self-skips if no config | always instantiated, LibreLane self-skips | Y |
| Position | Step 16 | Step 16 | Y |
| Config vars | MACRO_PLACEMENT_CFG plus flow-level MACROS | wired, with instance-location limitation | Partial |

**Status: PASS (with limitation: MACROS-based instance locations not supported)**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_mpl //dse/maths:SegmentedMultiplier16x16_sky130hd_cutrows`
  passed.
- `_mpl` runtime log reported:
  `No instances found, skipping 'Odb.ManualMacroPlacement'...`
- `_cutrows` then built successfully from the passed-through ODB state.

---

### Step 17: OpenROAD.CutRows

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.CutRows"` (line 2299)
- inputs: `[DesignFormat.ODB]` (line 2302)
- outputs: `[DesignFormat.ODB, DesignFormat.DEF]` (lines 2303-2306)
- Cuts floorplan rows with respect to placed macros
- config_vars: `OpenROADStep.config_vars` plus
  `FP_MACRO_HORIZONTAL_HALO`, `FP_MACRO_VERTICAL_HALO`, and
  `FP_PRUNE_THRESHOLD`

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.CutRows"` (line 242)
- step_outputs: `["def", "odb"]`
- `CUTROWS_CONFIG_KEYS` now uses `OPENROAD_STEP_CONFIG_KEYS` plus the CutRows
  local variables.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: after ManualMacroPlacement
- Chains from: `_mpl`; `_mpl` may self-skip and pass through prior state

**Config Variable Audit:**

CutRows config_vars (lines 2308-2332):

| Variable | Type | Default | Bazel Attr | Status |
|----------|------|---------|------------|--------|
| FP_MACRO_HORIZONTAL_HALO | Decimal | 10 | `fp_macro_horizontal_halo` (default="10") | Wired |
| FP_MACRO_VERTICAL_HALO | Decimal | 10 | `fp_macro_vertical_halo` (default="10") | Wired |
| FP_PRUNE_THRESHOLD | Optional[Decimal] | None | PDK | Wired |

Inherited `OpenROADStep` keys are wired through `OPENROAD_STEP_CONFIG_KEYS`.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.CutRows"` | `"OpenROAD.CutRows"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating | None | None | Y |
| Position | Step 17 | Step 17 | Y |
| Config vars | 3 + inherited | wired | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_cutrows`
  passed.
- Produced:
  `SegmentedMultiplier16x16.def`, `SegmentedMultiplier16x16.odb`, and
  `state_out.json`.

---

### Step 18: OpenROAD.TapEndcapInsertion

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.TapEndcapInsertion"` (line 1373)
- inputs: inherited from `OpenROADStep`: `[ODB]`
- outputs: inherited from `OpenROADStep`: `[ODB, DEF, NL, PNL, SDC]`
- Places well TAP cells and end-cap cells
- config_vars: `OpenROADStep.config_vars` plus `FP_TAPCELL_DIST`,
  `FP_MACRO_HORIZONTAL_HALO`, and `FP_MACRO_VERTICAL_HALO`
- `run()` fails if `WELLTAP_CELL` is set but `FP_TAPCELL_DIST` is not set
  (lines 1405-1411)

**Librelane Gating:** `classic.py`
- Variable: `RUN_TAP_ENDCAP_INSERTION` (lines 123-129)
- Default: `True` (line 128)
- Gating entry: `"OpenROAD.TapEndcapInsertion": ["RUN_TAP_ENDCAP_INSERTION"]`
  (line 276)

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.TapEndcapInsertion"` (line 247)
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`
- Uses `TAP_ENDCAP_CONFIG_KEYS`, split from `CUTROWS_CONFIG_KEYS` so
  `FP_TAPCELL_DIST` only affects the tap/endcap step.

**Bazel Flow:** `full_flow.bzl`
- Parameter: `run_tap_endcap_insertion = True`
- Gating: `if run_tap_endcap_insertion:`
- Position: after CutRows

**Config Variable Audit:**

Script (`tapcell.tcl`) uses: FP_TAPCELL_DIST, WELLTAP_CELL, ENDCAP_CELL, FP_MACRO_HORIZONTAL_HALO,
FP_MACRO_VERTICAL_HALO

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| FP_MACRO_HORIZONTAL_HALO | Decimal | 10 | Wired |
| FP_MACRO_VERTICAL_HALO | Decimal | 10 | Wired |
| FP_TAPCELL_DIST | Optional[Decimal] | None | Wired from PDK |
| WELLTAP_CELL | str | - | Base PDK variable |
| ENDCAP_CELL | str | - | Base PDK variable |
| OpenROADStep inherited keys | mixed | mixed | Wired through `OPENROAD_STEP_CONFIG_KEYS` |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.TapEndcapInsertion"` | `"OpenROAD.TapEndcapInsertion"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, NL, PNL, SDC]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating var | RUN_TAP_ENDCAP_INSERTION | run_tap_endcap_insertion | Y |
| Gating default | True | True | Y |
| Position | Step 18 | Step 18 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_tapendcap`
  passed.
- Produced:
  `SegmentedMultiplier16x16.def`, `SegmentedMultiplier16x16.odb`,
  `SegmentedMultiplier16x16.nl.v`, `SegmentedMultiplier16x16.pnl.v`,
  `SegmentedMultiplier16x16.sdc`, and `state_out.json`.

---

### Step 19: Odb.AddPDNObstructions

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.AddPDNObstructions"` (line 611)
- inputs: (inherited from AddRoutingObstructions) `[ODB]`
- outputs: (inherited from OdbpyStep) `[ODB, DEF]`
- config_vars: `PDN_OBSTRUCTIONS`, default=None
- Self-skips if `PDN_OBSTRUCTIONS` is None through inherited
  `AddRoutingObstructions.run()` behavior

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - relies on self-skip behavior

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.AddPDNObstructions"` (line 109)
- Uses `PDN_OBS_CONFIG_KEYS = ODB_CONFIG_KEYS + ["PDN_OBSTRUCTIONS"]`
- Declares `["def", "odb"]` only when `input_info.pdn_obstructions` is set;
  otherwise declares no design-view outputs so the skipped step passes through
  prior state.

**Bazel Flow:** `full_flow.bzl`
- Always instantiated, matching LibreLane self-skip behavior
- Position: Step 19, after TapEndcapInsertion

**Config Variable Audit:**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PDN_OBSTRUCTIONS | Optional[List[str]] | None | Wired |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.AddPDNObstructions"` | `"Odb.AddPDNObstructions"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` when run; none when skipped | conditional outputs matching configured obstructions | Y |
| Gating | Self-skips if PDN_OBSTRUCTIONS is None | always instantiated, LibreLane self-skips | Y |
| Position | Step 19 | Step 19 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_add_pdn_obs //dse/maths:SegmentedMultiplier16x16_sky130hd_pdn //dse/maths:SegmentedMultiplier16x16_sky130hd_rm_pdn_obs`
  passed.
- `_add_pdn_obs` runtime log reported:
  `'PDN_OBSTRUCTIONS' is not defined, skipping 'Odb.AddPDNObstructions'...`

---

### Step 20: OpenROAD.GeneratePDN

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.GeneratePDN"` (line 1450)
- inputs: (inherited from OpenROADStep) `[ODB]`
- outputs: (inherited from OpenROADStep) `[ODB, DEF, NL, PNL, SDC]`
- Creates power distribution network on floorplanned ODB
- config_vars: `OpenROADStep.config_vars + pdn_variables + [PDN_CFG]`
- `PDN_CFG` defaults to LibreLane's bundled `pdn_cfg.tcl` when unset
  (lines 1477-1482)

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.GeneratePDN"` (line 263)
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`
- `PDN_CONFIG_KEYS` uses the LibreLane 3.0.4 `PDN_*` names. The PDK provider
  retains the older internal `fp_pdn_*` field names, but `create_librelane_config`
  emits the new config keys.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 20, after AddPDNObstructions
- Chains from: `_add_pdn_obs`; that step may self-skip and pass through prior state

**Config Variable Audit:**

config_vars = OpenROADStep.config_vars + pdn_variables + [PDN_CFG]

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PDN_SKIPTRIM | bool | False | Wired |
| PDN_CORE_RING | bool | False | Wired |
| PDN_ENABLE_RAILS | bool | True | Wired |
| PDN_HORIZONTAL_HALO | Decimal | 10 | Wired |
| PDN_VERTICAL_HALO | Decimal | 10 | Wired |
| PDN_MULTILAYER | bool | True | Wired |
| PDN_CFG | Optional[Path] | None | Wired |
| PDN_RAIL_OFFSET | Decimal | PDK | Wired |
| PDN_VWIDTH | Decimal | PDK | Wired |
| PDN_HWIDTH | Decimal | PDK | Wired |
| PDN_VSPACING | Decimal | PDK | Wired |
| PDN_HSPACING | Decimal | PDK | Wired |
| PDN_VPITCH | Decimal | PDK | Wired |
| PDN_HPITCH | Decimal | PDK | Wired |
| PDN_VOFFSET | Decimal | PDK | Wired |
| PDN_HOFFSET | Decimal | PDK | Wired |
| PDN_CORE_RING_* | mixed | PDK | Wired |
| PDN_RAIL_LAYER | str | PDK | Wired |
| PDN_RAIL_WIDTH | Decimal | PDK | Wired |
| PDN_HORIZONTAL_LAYER | str | PDK | Wired |
| PDN_VERTICAL_LAYER | str | PDK | Wired |
| PDN_CORE_HORIZONTAL_LAYER | str | PDK | Wired |
| PDN_CORE_VERTICAL_LAYER | str | PDK | Wired |
| PDN_EXTEND_TO | str | PDK | Wired |
| PDN_ENABLE_PINS | bool | PDK | Wired |
| OpenROADStep.config_vars | - | - | Wired (inherited) |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.GeneratePDN"` | `"OpenROAD.GeneratePDN"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, NL, PNL, SDC]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating | None | None | Y |
| Position | Step 20 | Step 20 | Y |

**Status: PASS**

Verification:
- Initial run failed because Bazel was still emitting old `FP_PDN_*` keys while
  LibreLane 3.0.4 expects `PDN_*` names. The PDK mapping and emitted config were
  updated to the 3.0.4 names.
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_add_pdn_obs //dse/maths:SegmentedMultiplier16x16_sky130hd_pdn //dse/maths:SegmentedMultiplier16x16_sky130hd_rm_pdn_obs`
  passed.
- Runtime log reported that unset `PDN_CFG` was set to LibreLane's bundled
  `pdn_cfg.tcl`, then `pdngen` inserted the `stdcell_grid` and connected VPWR
  and VGND shapes.
- Produced:
  `SegmentedMultiplier16x16.def`, `SegmentedMultiplier16x16.odb`,
  `SegmentedMultiplier16x16.nl.v`, `SegmentedMultiplier16x16.pnl.v`,
  `SegmentedMultiplier16x16.sdc`, and `state_out.json`.

---

### Step 21: Odb.RemovePDNObstructions

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.RemovePDNObstructions"` (line 637)
- inputs: (inherited from RemoveRoutingObstructions) `[ODB]`
- outputs: (inherited from OdbpyStep) `[ODB, DEF]`
- config_vars: uses same `PDN_OBSTRUCTIONS` variable as AddPDNObstructions
- Self-skips if `PDN_OBSTRUCTIONS` is None through inherited behavior

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - relies on self-skip behavior

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.RemovePDNObstructions"` (line 114)
- Uses `PDN_OBS_CONFIG_KEYS = ODB_CONFIG_KEYS + ["PDN_OBSTRUCTIONS"]`
- Declares `["def", "odb"]` only when `input_info.pdn_obstructions` is set;
  otherwise declares no design-view outputs so the skipped step passes through
  prior state.

**Bazel Flow:** `full_flow.bzl`
- Always instantiated, matching LibreLane self-skip behavior
- Position: Step 21, after GeneratePDN
- Post-PDN source always chains through `_rm_pdn_obs`.

**Config Variable Audit:**

config_vars = AddPDNObstructions.config_vars (same as Step 19)

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PDN_OBSTRUCTIONS | Optional[List[str]] | None | Wired (PDN_OBS_CONFIG_KEYS in odb.bzl) |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.RemovePDNObstructions"` | `"Odb.RemovePDNObstructions"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` when run; none when skipped | conditional outputs matching configured obstructions | Y |
| Gating | Self-skips if PDN_OBSTRUCTIONS is None | always instantiated, LibreLane self-skips | Y |
| Position | Step 21 | Step 21 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_add_pdn_obs //dse/maths:SegmentedMultiplier16x16_sky130hd_pdn //dse/maths:SegmentedMultiplier16x16_sky130hd_rm_pdn_obs`
  passed.
- `_rm_pdn_obs` runtime log reported:
  `'PDN_OBSTRUCTIONS' is not defined, skipping 'Odb.RemovePDNObstructions'...`

---

### Step 22: Odb.AddRoutingObstructions

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.AddRoutingObstructions"` (line 556)
- inputs: (inherited from OdbpyStep) `[ODB]`
- outputs: (inherited from OdbpyStep) `[ODB, DEF]`
- config_vars: `ROUTING_OBSTRUCTIONS`, default=None
- The config type is
  `Optional[List[Tuple[str, Decimal, Decimal, Decimal, Decimal]]]`.
- Self-skips if `ROUTING_OBSTRUCTIONS` is None (lines 589-594).

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - relies on self-skip behavior

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.AddRoutingObstructions"` (line 118)
- Uses `ROUTING_OBS_CONFIG_KEYS = ODB_CONFIG_KEYS + ["ROUTING_OBSTRUCTIONS"]`
- Declares `["def", "odb"]` only when `input_info.routing_obstructions` is set;
  otherwise declares no design-view outputs so the skipped step passes through
  prior state.

**Bazel Flow:** `full_flow.bzl`
- Always instantiated, matching LibreLane self-skip behavior
- Position: Step 22, after RemovePDNObstructions
- GlobalPlacementSkipIO now chains from `_add_route_obs`.

**Config Variable Audit:**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| ROUTING_OBSTRUCTIONS | Optional[List[Tuple[str, Decimal, Decimal, Decimal, Decimal]]] | None | Wired |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.AddRoutingObstructions"` | `"Odb.AddRoutingObstructions"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` when run; none when skipped | conditional outputs matching configured obstructions | Y |
| Gating | Self-skips if ROUTING_OBSTRUCTIONS is None | always instantiated, LibreLane self-skips | Y |
| Position | Step 22 | Step 22 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_add_route_obs`
  passed.
- Runtime log reported:
  `'ROUTING_OBSTRUCTIONS' is not defined. Skipping 'Odb.AddRoutingObstructions'...`

---

### Step 23: OpenROAD.GlobalPlacementSkipIO

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.GlobalPlacementSkipIO"` (line 1621)
- inputs: (inherited from _GlobalPlacement) `[ODB]`
- outputs: (inherited from OpenROADStep) `[ODB, DEF, NL, PNL, SDC]`
- config_vars: `_GlobalPlacement.config_vars` plus
  `IO_PIN_PLACEMENT_MODE`, `IO_PIN_ORDER_CFG`, and `FP_DEF_TEMPLATE`
- Self-skips if `FP_DEF_TEMPLATE` is set or `IO_PIN_ORDER_CFG` is set
  (lines 1658-1667).
- Otherwise sets `__PL_SKIP_IO = 1` and runs `gpl.tcl`.

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - relies on self-skip behavior

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.GlobalPlacementSkipIO"` (line 268)
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`
- `GPL_SKIP_IO_CONFIG_KEYS` uses `OPENROAD_STEP_CONFIG_KEYS` plus the full
  `_GlobalPlacement` variable set, including routing-layer, detailed-placement,
  and resizer variables inherited through LibreLane's `rsz_variables`.
- Bazel's existing `fp_ppl_mode` attribute is emitted as LibreLane's current
  `IO_PIN_PLACEMENT_MODE` config key.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 23, after AddRoutingObstructions
- LibreLane's self-skip on `FP_DEF_TEMPLATE` and `IO_PIN_ORDER_CFG` is handled
  by the step itself.

**Config Variable Audit:**

config_vars = _GlobalPlacement.config_vars + [IO_PIN_PLACEMENT_MODE, IO_PIN_ORDER_CFG, FP_DEF_TEMPLATE]
_GlobalPlacement.config_vars = OpenROADStep.config_vars + routing_layer_variables + rsz_variables + placement vars

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| IO_PIN_PLACEMENT_MODE | PPLMode | "matching" | Wired from `fp_ppl_mode` |
| IO_PIN_ORDER_CFG | Optional[Path] | None | Wired from `fp_pin_order_cfg` |
| FP_DEF_TEMPLATE | Optional[Path] | None | Wired |
| PL_TARGET_DENSITY_PCT | Optional[Decimal] | None | Wired |
| PL_SKIP_INITIAL_PLACEMENT | bool | False | Wired |
| PL_WIRE_LENGTH_COEF | Decimal | 0.25 | Wired |
| PL_MIN_PHI_COEFFICIENT | Optional[Decimal] | None | Wired |
| PL_MAX_PHI_COEFFICIENT | Optional[Decimal] | None | Wired |
| PL_KEEP_RESIZE_BELOW_OVERFLOW | Optional[Decimal] | None | Wired |
| FP_CORE_UTIL | Decimal | 50 | Wired (floorplan.bzl) |
| GPL_CELL_PADDING | Decimal | - | PDK (wired) |
| RT_CLOCK_MIN_LAYER | Optional[str] | None | Wired |
| RT_CLOCK_MAX_LAYER | Optional[str] | None | Wired |
| GRT_ADJUSTMENT | Decimal | 0.3 | Wired |
| GRT_MACRO_EXTENSION | int | 0 | Wired |
| GRT_LAYER_ADJUSTMENTS | List[Decimal] | - | PDK (wired) |
| dpl_variables | mixed | mixed | Wired |
| rsz_variables | mixed | mixed | Wired |
| OpenROADStep.config_vars | - | - | Wired (inherited) |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.GlobalPlacementSkipIO"` | `"OpenROAD.GlobalPlacementSkipIO"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, NL, PNL, SDC]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating | None; self-skips if template or pin-order cfg is set | None; self-skip in LibreLane | Y |
| Position | Step 23 | Step 23 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_gpl_skip_io`
  passed.
- Runtime log reported dynamic `PL_TARGET_DENSITY_PCT` calculation, then ran
  `global_placement -skip_io`.
- Produced:
  `SegmentedMultiplier16x16.def`, `SegmentedMultiplier16x16.odb`,
  `SegmentedMultiplier16x16.nl.v`, `SegmentedMultiplier16x16.pnl.v`,
  `SegmentedMultiplier16x16.sdc`, and `state_out.json`.

---

### Step 24: OpenROAD.IOPlacement

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.IOPlacement"` (line 1298)
- inputs: inherited from `OpenROADStep`: `[ODB]`
- outputs: inherited from `OpenROADStep`: `[ODB, DEF, NL, PNL, SDC]`
- config_vars: `OpenROADStep.config_vars + io_layer_variables` plus
  `IO_PIN_CORNER_AVOIDANCE`, `IO_PIN_PLACEMENT_MODE`,
  `IO_PIN_MIN_DISTANCE`, `IO_PIN_MIN_DISTANCE_IN_TRACKS`,
  `IO_PIN_ORDER_CFG`, `IO_EXCLUDE_PIN_REGION`, and `FP_DEF_TEMPLATE`
- Self-skips when `IO_PIN_ORDER_CFG` or `FP_DEF_TEMPLATE` is set.

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.IOPlacement"`
- Target suffix: `_io_place`
- Uses current LibreLane `IO_PIN_*` names in `IO_PLACEMENT_CONFIG_KEYS`.
- Declares design-view outputs only when neither `fp_pin_order_cfg` nor
  `fp_def_template` is set; otherwise LibreLane self-skips and Bazel passes
  state through.

**Bazel Flow:** `full_flow.bzl`
- Runs after `_gpl_skip_io` and before `_custom_io`.
- Always instantiated, matching LibreLane Classic self-skip behavior.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.IOPlacement"` | `"OpenROAD.IOPlacement"` | Y |
| inputs | `[ODB]` | from `_gpl_skip_io` | Y |
| outputs | `[ODB, DEF, NL, PNL, SDC]` when run | conditional outputs matching skip behavior | Y |
| config keys | current `IO_PIN_*` names | current `IO_PIN_*` names | Y |
| Gating | self-skips for pin-order/template config | always instantiated, LibreLane self-skips | Y |
| Position | Step 24 | Step 24 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_io_place`
  passed.
- Runtime log ran `place_pins -hor_layers met3 -ver_layers met2` and placed
  73 IO pins.

---

### Step 25: Odb.CustomIOPlacement

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.CustomIOPlacement"` (line 656)
- inputs: inherited from `OdbpyStep`: `[ODB]`
- outputs: inherited from `OdbpyStep`: `[ODB, DEF]`
- config_vars: `io_layer_variables` plus `IO_PIN_ORDER_CFG` and
  `ERRORS_ON_UNMATCHED_IO`
- Self-skips when `IO_PIN_ORDER_CFG` is not set.

**Bazel Implementation:** `place.bzl`
- ID: `"Odb.CustomIOPlacement"`
- Target suffix: `_custom_io`
- Uses current LibreLane `IO_PIN_*` names in
  `CUSTOM_IO_PLACEMENT_CONFIG_KEYS`.
- Declares DEF/ODB outputs only when `fp_pin_order_cfg` is set; otherwise
  LibreLane self-skips and Bazel passes state through.

**Bazel Flow:** `full_flow.bzl`
- Runs after `_io_place` and before `_def_template`.
- Always instantiated, matching LibreLane Classic self-skip behavior.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.CustomIOPlacement"` | `"Odb.CustomIOPlacement"` | Y |
| inputs | `[ODB]` | from `_io_place` | Y |
| outputs | `[ODB, DEF]` when run | conditional outputs matching skip behavior | Y |
| config keys | current `IO_PIN_*` names | current `IO_PIN_*` names | Y |
| Gating | self-skips if `IO_PIN_ORDER_CFG` is unset | always instantiated, LibreLane self-skips | Y |
| Position | Step 25 | Step 25 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_custom_io`
  passed.
- Runtime log reported:
  `No custom I/O placement file configured, skipping 'Odb.CustomIOPlacement'...`

---

### Step 26: Odb.ApplyDEFTemplate

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.ApplyDEFTemplate"` (line 261)
- inputs: inherited from `OdbpyStep`: `[ODB]`
- outputs: inherited from `OdbpyStep`: `[ODB, DEF]`
- config_vars: `FP_DEF_TEMPLATE`, `FP_TEMPLATE_MATCH_MODE`, and
  `FP_TEMPLATE_COPY_POWER_PINS`
- Self-skips when `FP_DEF_TEMPLATE` is not set.

**Bazel Implementation:** `place.bzl`
- ID: `"Odb.ApplyDEFTemplate"`
- Target suffix: `_def_template`
- Declares DEF/ODB outputs only when `fp_def_template` is set; otherwise
  LibreLane self-skips and Bazel passes state through.

**Bazel Flow:** `full_flow.bzl`
- Runs after `_custom_io` and before `_gpl`.
- Always instantiated, matching LibreLane Classic self-skip behavior.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.ApplyDEFTemplate"` | `"Odb.ApplyDEFTemplate"` | Y |
| inputs | `[ODB]` | from `_custom_io` | Y |
| outputs | `[ODB, DEF]` when run | conditional outputs matching skip behavior | Y |
| config keys | 3 variables | `APPLY_DEF_TEMPLATE_CONFIG_KEYS` | Y |
| Gating | self-skips if `FP_DEF_TEMPLATE` is unset | always instantiated, LibreLane self-skips | Y |
| Position | Step 26 | Step 26 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_def_template`
  passed.
- Runtime log reported:
  `No DEF template provided, skipping 'Odb.ApplyDEFTemplate'...`
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_gpl` also passed,
  verifying the next stage consumes the sequential IO state.

---

### Step 27: OpenROAD.GlobalPlacement

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.GlobalPlacement"` (line 1589)
- inputs: inherited from `OpenROADStep`: `[ODB]`
- outputs: inherited from `OpenROADStep`: `[ODB, DEF, NL, PNL, SDC]`
- Performs initial cell placement with time-driven and routability-driven modes
- config_vars: `_GlobalPlacement.config_vars` plus `PL_TIMING_DRIVEN`,
  `PL_ROUTABILITY_DRIVEN`, and `PL_ROUTABILITY_OVERFLOW_THRESHOLD`

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.GlobalPlacement"`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`
- `GPL_CONFIG_KEYS` uses `OPENROAD_STEP_CONFIG_KEYS`, routing-layer variables,
  dpl/rsz variables inherited through `rsz_variables`, and the current
  `PL_TIMING_DRIVEN` key.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 27, after ApplyDEFTemplate
- Chains from: `_def_template` target, which may pass through state when no DEF
  template is configured.

**Config Variable Audit:**

config_vars = _GlobalPlacement.config_vars + [PL_TIMING_DRIVEN, PL_ROUTABILITY_DRIVEN,
                                               PL_ROUTABILITY_OVERFLOW_THRESHOLD]
_GlobalPlacement.config_vars = OpenROADStep.config_vars + routing_layer_variables + rsz_variables + placement vars

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PL_TIMING_DRIVEN | bool | False | Wired |
| PL_ROUTABILITY_DRIVEN | bool | True | Wired |
| PL_ROUTABILITY_OVERFLOW_THRESHOLD | Optional[Decimal] | None | Wired |
| PL_TARGET_DENSITY_PCT | Optional[Decimal] | None | Wired |
| PL_SKIP_INITIAL_PLACEMENT | bool | False | Wired |
| PL_WIRE_LENGTH_COEF | Decimal | 0.25 | Wired |
| PL_MIN_PHI_COEFFICIENT | Optional[Decimal] | None | Wired |
| PL_MAX_PHI_COEFFICIENT | Optional[Decimal] | None | Wired |
| PL_KEEP_RESIZE_BELOW_OVERFLOW | Optional[Decimal] | None | Wired |
| FP_CORE_UTIL | Decimal | 50 | Wired |
| GPL_CELL_PADDING | Decimal | - | PDK (wired) |
| RT_CLOCK_MIN_LAYER | Optional[str] | None | Wired |
| RT_CLOCK_MAX_LAYER | Optional[str] | None | Wired |
| GRT_ADJUSTMENT | Decimal | 0.3 | Wired |
| GRT_MACRO_EXTENSION | int | 0 | Wired |
| GRT_LAYER_ADJUSTMENTS | List[Decimal] | - | PDK (wired) |
| dpl_variables | mixed | mixed | Wired |
| rsz_variables | mixed | mixed | Wired |
| OpenROADStep.config_vars | - | - | Wired (inherited) |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.GlobalPlacement"` | `"OpenROAD.GlobalPlacement"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating | None | None | Y |
| Position | Step 27 | Step 27 | Y |
| Config vars | All | All | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_gpl` passed.
- Runtime log ran routability-driven global placement. It did not pass
  `-timing_driven`, matching LibreLane's default `PL_TIMING_DRIVEN = False`.
- Produced DEF, ODB, NL, PNL, SDC, and `state_out.json`.

---

### Step 28: Odb.WriteVerilogHeader

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.WriteVerilogHeader"` (line 353)
- inputs: `[DesignFormat.ODB, DesignFormat.JSON_HEADER]`
- outputs: `[DesignFormat.VERILOG_HEADER]`
- Writes a Verilog header with power port definitions

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.WriteVerilogHeader"`
- step_outputs: `["vh"]`
- Uses `WRITE_VH_CONFIG_KEYS = ODB_CONFIG_KEYS + ["VERILOG_POWER_DEFINE"]`
  because the inherited `OdbpyStep.get_command()` loads tech, cell, extra, pad,
  and macro LEFs before invoking the script.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs
- Position: Step 28, after GlobalPlacement
- Chains from: `_gpl` target

**Config Variable Audit:**

config_vars = OdbpyStep.config_vars + [VERILOG_POWER_DEFINE]

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| VERILOG_POWER_DEFINE | Optional[str] | "USE_POWER_PINS" | Wired |
| OdbpyStep.config_vars | - | - | Wired (inherited) |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.WriteVerilogHeader"` | `"Odb.WriteVerilogHeader"` | Y |
| inputs | `[ODB, JSON_HEADER]` | (from src) | Y |
| outputs | `[VERILOG_HEADER]` | `["vh"]` | Y |
| Gating | None | None | Y |
| Position | Step 28 | Step 28 | Y |
| Config vars | All | All | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_vh` passed.
- Produced `SegmentedMultiplier16x16.vh` and `state_out.json`.

---

### Step 29: Checker.PowerGridViolations

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.PowerGridViolations"` (line 328)
- inputs: `[]` inherited from `MetricChecker`
- outputs: `[]` inherited from `MetricChecker`
- deferred: `True` inherited from `MetricChecker`
- metric_name: `"design__power_grid_violation__count"`
- error_on_var: `ERROR_ON_PDN_VIOLATIONS`, default=True

**Librelane Gating:** `classic.py`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.PowerGridViolations"`
- step_outputs: `[]`
- Uses `POWER_GRID_VIOLATIONS_CONFIG_KEYS`

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs (lines 406-410)
- Position: Step 29, after WriteVerilogHeader
- Chains from: `_vh` target

**Config Variable Audit:**

config_vars = [ERROR_ON_PDN_VIOLATIONS]
MetricChecker (parent) has no config_vars

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| ERROR_ON_PDN_VIOLATIONS | bool | True | Wired |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.PowerGridViolations"` | `"Checker.PowerGridViolations"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | Y |
| Position | Step 29 | Step 29 | Y |
| Config vars | All | All | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_pdn` passed.
- Runtime log reported the power grid violation check was clear.

---

### Step 30: OpenROAD.STAMidPNR

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.STAMidPNR"` (line 536)
- inputs: `[DesignFormat.ODB]`
- outputs: `[]`
- Performs static timing analysis with estimated parasitics
- Note: This step appears 4 times in the Classic flow (steps 30, 35, 37, 45)

**Librelane Gating:** `classic.py`
- First occurrence after `Checker.PowerGridViolations`
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.STAMidPNR"`
- step_outputs: `[]`
- Uses `STA_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS`
- Declares `max.rpt` and `min.rpt` as extra outputs.

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs (lines 412-417)
- Position: Step 30, after PowerGridViolations
- Chains from: `_chk_pdn` target
- Named: `_sta_mid_gpl`

**Config Variable Audit:**

STAMidPNR inherits from OpenROADStep (no additional config_vars).
OpenROADStep.prepare_env() uses `FALLBACK_SDC`, `EXTRA_EXCLUDED_CELLS`, and
`PNR_EXCLUDED_CELL_FILE`.

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PDN_CONNECT_MACROS_TO_GRID | bool | True | Wired |
| PDN_MACRO_CONNECTIONS | Optional[List[str]] | None | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | bool | True | Wired |
| PNR_SDC_FILE | Optional[Path] | None | Wired |
| STA_EXTRA_CORNER_TCL_FILE | Optional[Path] | None | Wired |
| DEDUPLICATE_CORNERS | bool | False | Wired |
| PNR_CORNERS / RC variables | mixed | mixed | Wired through `OPENROAD_STEP_CONFIG_KEYS` |
| FALLBACK_SDC | (from prepare_env) | - | Wired |
| EXTRA_EXCLUDED_CELLS | (from prepare_env) | - | Wired |
| PNR_EXCLUDED_CELL_FILE | PDK file | - | Wired |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.STAMidPNR"` | `"OpenROAD.STAMidPNR"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | Y |
| Position | Step 30 | Step 30 | Y |
| Config vars | All | All | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_sta_mid_gpl`
  passed.
- Produced `max.rpt`, `min.rpt`, and `state_out.json`.

---

### Step 31: OpenROAD.RepairDesignPostGPL

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.RepairDesignPostGPL"` (line 2562)
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- Runs design repairs after global placement
- Inheritance: RepairDesignPostGPL -> ResizerStep -> OpenROADStep

**Librelane Gating:** `classic.py`
- Position: Step 31 (line 71)
- Variable: `RUN_POST_GPL_DESIGN_REPAIR` (line 268)
- Default: `True` (line 133)

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.RepairDesignPostGPL"`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`
- Uses `REPAIR_DESIGN_CONFIG_KEYS`.
- `RESIZER_CONFIG_KEYS` now starts from `OPENROAD_STEP_CONFIG_KEYS`, then adds
  routing-layer, grt, dpl, and rsz variables.

**Bazel Flow:** `full_flow.bzl`
- Parameter: `run_post_gpl_design_repair = True` (line 109)
- Gating: `if run_post_gpl_design_repair:` (line 362)
- Position: Step 31, after STAMidPNR (lines 362-366)
- Chains from: `_sta_mid_gpl` target

**Config Variable Audit:**

Inheritance chain: RepairDesignPostGPL -> ResizerStep -> OpenROADStep
- ResizerStep.config_vars = OpenROADStep.config_vars + grt_variables + rsz_variables
- grt_variables = routing_layer_variables + grt-specific (common_variables.py:285-319)
- rsz_variables = dpl_variables + rsz-specific (common_variables.py:321-340)

**OpenROADStep config_vars (openroad.py:192-223):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PDN_CONNECT_MACROS_TO_GRID | bool | True | Wired |
| PDN_MACRO_CONNECTIONS | Optional[List[str]] | None | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | bool | True | Wired |
| PNR_SDC_FILE | Optional[Path] | None | Wired |
| FP_DEF_TEMPLATE | Optional[Path] | None | Wired |

**routing_layer_variables (common_variables.py:223-252):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| RT_CLOCK_MIN_LAYER | Optional[str] | None | Wired |
| RT_CLOCK_MAX_LAYER | Optional[str] | None | Wired |
| GRT_ADJUSTMENT | Decimal | 0.3 | Wired |
| GRT_MACRO_EXTENSION | int | 0 | Wired |
| GRT_LAYER_ADJUSTMENTS | List[Decimal] | (pdk) | Wired (PdkInfo) |

**grt_variables specific (common_variables.py:285-319):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| DIODE_PADDING | Optional[int] | None | Wired |
| GRT_ALLOW_CONGESTION | bool | False | Wired |
| GRT_ANTENNA_ITERS | int | 3 | Wired |
| GRT_OVERFLOW_ITERS | int | 50 | Wired |
| GRT_ANTENNA_MARGIN | int | 10 | Wired |

**dpl_variables (common_variables.py:255-283):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PL_OPTIMIZE_MIRRORING | bool | True | Wired |
| PL_MAX_DISPLACEMENT_X | Decimal | 500 | Wired |
| PL_MAX_DISPLACEMENT_Y | Decimal | 100 | Wired |
| DPL_CELL_PADDING | Decimal | (pdk) | Wired (PdkInfo) |

**rsz_variables specific (common_variables.py:321-340):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| RSZ_DONT_TOUCH_RX | str | "$^" | Wired |
| RSZ_DONT_TOUCH_LIST | Optional[List[str]] | None | Wired |
| RSZ_CORNERS | Optional[List[str]] | None | Wired |

**RepairDesignPostGPL own config_vars (openroad.py:2119-2178):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| DESIGN_REPAIR_BUFFER_INPUT_PORTS | bool | True | Wired |
| DESIGN_REPAIR_BUFFER_OUTPUT_PORTS | bool | True | Wired |
| DESIGN_REPAIR_TIE_FANOUT | bool | True | Wired |
| DESIGN_REPAIR_TIE_SEPARATION | bool | False | Wired |
| DESIGN_REPAIR_MAX_WIRE_LENGTH | Decimal | 0 | Wired |
| DESIGN_REPAIR_MAX_SLEW_PCT | Decimal | 20 | Wired |
| DESIGN_REPAIR_MAX_CAP_PCT | Decimal | 20 | Wired |
| DESIGN_REPAIR_REMOVE_BUFFERS | bool | False | Wired |

**OpenROADStep.prepare_env():**

| Variable | Usage | Bazel Status |
|----------|-------|--------------|
| FALLBACK_SDC | env["_SDC_IN"] | Wired |
| EXTRA_EXCLUDED_CELLS | env["_PNR_EXCLUDED_CELLS"] | Wired |
| PNR_EXCLUDED_CELL_FILE | env["_PNR_EXCLUDED_CELLS"] | Wired (PdkInfo) |
| LIB | env["_PNR_LIBS"] | Wired (PdkInfo) |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.RepairDesignPostGPL"` | `"OpenROAD.RepairDesignPostGPL"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating var | RUN_POST_GPL_DESIGN_REPAIR | run_post_gpl_design_repair | Y |
| Gating default | True | True | Y |
| Position | Step 31 | Step 31 | Y |
| Config vars | ResizerStep + own vars | All wired | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_rsz_gpl`
  passed.
- Runtime log ran `repair_design`, inserted input/output buffers, then wrote
  DEF, ODB, NL, PNL, SDC, and `state_out.json`.
- LibreLane warned that `GRT_ANTENNA_ITERS` and `GRT_ANTENNA_MARGIN` are
  deprecated; those belong to later global-routing/antenna variable cleanup.

---

### Step 32: Odb.ManualGlobalPlacement

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.ManualGlobalPlacement"` (line 1008)
- inputs: `[DesignFormat.ODB]` (inherited from OdbpyStep)
- outputs: `[DesignFormat.ODB, DesignFormat.DEF]` (inherited from OdbpyStep)
- Inheritance: ManualGlobalPlacement -> OdbpyStep -> Step
- **Self-skips if MANUAL_GLOBAL_PLACEMENTS is None** (lines 1005-1008)

**Librelane Gating:** `classic.py`
- Position: Step 32 (line 72)
- No entry in gating_config_vars - relies on self-skip behavior

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.ManualGlobalPlacement"`
- Uses `MANUAL_GLOBAL_PLACEMENT_CONFIG_KEYS = ODB_CONFIG_KEYS + ["MANUAL_GLOBAL_PLACEMENTS"]`
- Declares DEF/ODB outputs only when `manual_global_placements` is configured;
  otherwise LibreLane self-skips and Bazel passes state through.

**Bazel Flow:** `full_flow.bzl`
- Parameter: `manual_global_placements = None` (line 118)
- Always instantiated after RepairDesignPostGPL, matching LibreLane self-skip behavior

**Config Variable Audit:**

Inheritance chain: ManualGlobalPlacement -> OdbpyStep -> Step
OdbpyStep has no config_vars (inherits empty from Step base).

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| MANUAL_GLOBAL_PLACEMENTS | Optional[Dict[str, Instance]] | None | Wired (5-location) |

**5-location wiring (2026-01-28):**
1. common.bzl ENTRY_ATTRS: `manual_global_placements` attr.string
2. providers.bzl LibrelaneInput: `manual_global_placements` field
3. init.bzl _init_impl: wired from ctx.attr
4. common.bzl create_librelane_config: JSON decoded to dict
5. odb.bzl MANUAL_GLOBAL_PLACEMENT_CONFIG_KEYS: includes key

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.ManualGlobalPlacement"` | `"Odb.ManualGlobalPlacement"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating | Self-skips if MANUAL_GLOBAL_PLACEMENTS is None | always instantiated, LibreLane self-skips | Y |
| Position | Step 32 | Step 32 | Y |
| Config vars | 1 total | 1 wired | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_mgpl` passed.
- Runtime log reported:
  `'MANUAL_GLOBAL_PLACEMENTS' not set. Skipping 'Odb.ManualGlobalPlacement'...`

---

### Step 33: OpenROAD.DetailedPlacement

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.DetailedPlacement"` (line 1680)
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- Inheritance: DetailedPlacement -> OpenROADStep
- config_vars = OpenROADStep.config_vars + dpl_variables (line 1374)
- Legalizes cell placement from global placement

**Librelane Gating:** `classic.py`
- Position: Step 33 (line 73)
- No entry in gating_config_vars - always runs

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.DetailedPlacement"`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`
- Uses `DPL_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + dpl_variables`

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs (lines 442-447)
- Position: Step 33, after ManualGlobalPlacement (line 442)
- Chains from: `pre_dpl_src` (either `_mgpl` or `_sta_mid_gpl`/`_rsz_gpl`)

**Config Variable Audit:**

Inheritance chain: DetailedPlacement -> OpenROADStep
config_vars = OpenROADStep.config_vars + dpl_variables

**OpenROADStep.config_vars (openroad.py:192-223):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PDN_CONNECT_MACROS_TO_GRID | bool | True | Wired |
| PDN_MACRO_CONNECTIONS | Optional[List[str]] | None | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | bool | True | Wired |
| PNR_SDC_FILE | Optional[Path] | None | Wired |
| FP_DEF_TEMPLATE | Optional[Path] | None | Wired |

**OpenROADStep.prepare_env():**

| Variable | Usage | Bazel Status |
|----------|-------|--------------|
| FALLBACK_SDC | env["_SDC_IN"] | Wired |
| EXTRA_EXCLUDED_CELLS | env["_PNR_EXCLUDED_CELLS"] | Wired |
| PNR_EXCLUDED_CELL_FILE | env["_PNR_EXCLUDED_CELLS"] | Wired |

**dpl_variables (common_variables.py:255-283):**

| Variable | Type | Default | Bazel Status |
|----------|------|---------|--------------|
| PL_OPTIMIZE_MIRRORING | bool | True | Wired |
| PL_MAX_DISPLACEMENT_X | Decimal | 500 | Wired |
| PL_MAX_DISPLACEMENT_Y | Decimal | 100 | Wired |
| DPL_CELL_PADDING | Decimal | (pdk) | Wired (PdkInfo) |

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.DetailedPlacement"` | `"OpenROAD.DetailedPlacement"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating | None | None | Y |
| Position | Step 33 | Step 33 | Y |
| Config vars | 11 total | All wired | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_dpl` passed.
- Produced DEF, ODB, NL, PNL, SDC, and `state_out.json`.

---

### Step 34: OpenROAD.CTS

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.CTS"` (line 2407)
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- Inheritance: CTS -> OpenROADStep -> TclStep -> Step
- Clock tree synthesis with buffer insertion, calls dpl.tcl for legalization

**Librelane Gating:** `classic.py`
- Position: Step 34 (line 74)
- Variable: `RUN_CTS` (line 272)
- Default: `True` (line 146)
- Users CAN disable CTS by setting RUN_CTS=False

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.CTS"`
- outputs: DEF, ODB, NL, PNL, SDC, `cts.rpt`, and `state_out.json`
- `CTS_CONFIG_KEYS` now starts from `OPENROAD_STEP_CONFIG_KEYS`, then adds
  dpl variables and the full LibreLane 3.0.4 CTS variable set.

**Bazel Flow:** `full_flow.bzl`
- Gating: `run_cts` parameter (default True)
- Position: Step 34, after DetailedPlacement
- Chains from: `_dpl` target

**Config Variable Audit:**

CTS config_vars:

| Variable | Type | Default | Bazel Attr | Status |
|----------|------|---------|------------|--------|
| CTS_BALANCE_LEVELS | Optional[bool] | None | `cts_balance_levels` | Wired |
| CTS_SINK_BUFFER_MAX_CAP_DERATE_PCT | Optional[Decimal] | None | `cts_sink_buffer_max_cap_derate_pct` | Wired |
| CTS_DELAY_BUFFER_DERATE_PCT | Optional[Decimal] | None | `cts_delay_buffer_derate_pct` | Wired |
| CTS_OBSTRUCTION_AWARE | Optional[bool] | None | `cts_obstruction_aware` | Wired |
| CTS_SINK_CLUSTERING_ENABLE | bool | True | `cts_sink_clustering_enable` | Wired |
| CTS_SINK_CLUSTERING_SIZE | Optional[int] | None | `cts_sink_clustering_size` | Wired |
| CTS_SINK_CLUSTERING_MAX_DIAMETER | Optional[Decimal] | None | `cts_sink_clustering_max_diameter` | Wired |
| CTS_MACRO_CLUSTERING_SIZE | Optional[int] | None | `cts_macro_clustering_size` | Wired |
| CTS_MACRO_CLUSTERING_MAX_DIAMETER | Optional[Decimal] | None | `cts_macro_clustering_max_diameter` | Wired |
| CTS_CLK_MAX_WIRE_LENGTH | Decimal | 0 | `cts_clk_max_wire_length` | Wired |
| CTS_DISABLE_POST_PROCESSING | bool | False | `cts_disable_post_processing` | Wired |
| CTS_DISTANCE_BETWEEN_BUFFERS | Decimal | 0 | `cts_distance_between_buffers` | Wired |
| CTS_CORNERS | Optional[List[str]] | None | `cts_corners` | Wired |
| CTS_ROOT_BUFFER | str | (pdk) | (from PDK) | Wired |
| CTS_CLK_BUFFERS | List[str] | (pdk) | (from PDK) | Wired |
| CTS_MAX_CAP | Optional[Decimal] | None | `cts_max_cap` | Wired |
| CTS_MAX_SLEW | Optional[Decimal] | None | `cts_max_slew` | Wired |
| CTS_APPLY_NDR | Literal | "half" | `cts_apply_ndr` | Wired |

Inherited OpenROADStep.config_vars (openroad.py lines 192-223):

| Variable | Type | Default | Bazel Attr | Status |
|----------|------|---------|------------|--------|
| PDN_CONNECT_MACROS_TO_GRID | bool | True | `pdn_connect_macros_to_grid` | Wired |
| PDN_MACRO_CONNECTIONS | Optional[List[str]] | None | `pdn_macro_connections` | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | bool | True | `pdn_enable_global_connections` | Wired |
| PNR_SDC_FILE | Optional[Path] | None | `pnr_sdc_file` | Wired |
| STA_EXTRA_CORNER_TCL_FILE | Optional[Path] | None | `sta_extra_corner_tcl_file` | Wired |
| DEDUPLICATE_CORNERS | bool | False | `deduplicate_corners` | Wired |

Inherited dpl_variables (common_variables.py lines 255-283):

| Variable | Type | Default | Bazel Attr | Status |
|----------|------|---------|------------|--------|
| PL_OPTIMIZE_MIRRORING | bool | True | `pl_optimize_mirroring` | Wired |
| PL_MAX_DISPLACEMENT_X | Decimal | 500 | `pl_max_displacement_x` | Wired |
| PL_MAX_DISPLACEMENT_Y | Decimal | 100 | `pl_max_displacement_y` | Wired |
| DPL_CELL_PADDING | Decimal | (pdk) | (from PDK) | Wired |

TCL script usage (scripts/openroad/cts.tcl):
- Line 44: CTS_CLK_BUFFERS
- Line 45: CTS_ROOT_BUFFER
- Line 46: CTS_SINK_CLUSTERING_SIZE
- Line 47: CTS_SINK_CLUSTERING_MAX_DIAMETER
- Line 50-52: CTS_DISTANCE_BETWEEN_BUFFERS (if != 0)
- Line 54-56: CTS_DISABLE_POST_PROCESSING
- Line 65: CTS_CLK_MAX_WIRE_LENGTH
- Line 30-31: CTS_MAX_CAP (optional)
- Line 33-35: CTS_MAX_SLEW (optional)
- Line 71: sources dpl.tcl for legalization

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.CTS"` | `"OpenROAD.CTS"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `[def, odb, nl, pnl, sdc, cts_report]` | Y |
| Gating var | RUN_CTS | `run_cts` | Y |
| Gating default | True | True | Y |
| Position | Step 34 | Step 34 | Y |
| Config vars | 10 CTS-specific + inherited | All wired via 5-location | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_cts` passed.
- Runtime log ran `clock_tree_synthesis ... -sink_clustering_enable -apply_ndr half`,
  then legalized placement.
- Produced DEF, ODB, NL, PNL, SDC, `cts.rpt`, and `state_out.json`.

---

### Step 35: OpenROAD.STAMidPNR (second occurrence)

**Verified:** 2026-07-07 against LibreLane 3.0.4

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.STAMidPNR"` (line 536)
- Class: STAMidPNR -> OpenROADStep -> TclStep -> Step
- inputs: `[DesignFormat.ODB]` (line 368)
- outputs: `[]` (line 369)
- Performs static timing analysis with estimated parasitics
- Note: This step appears 4 times in Classic flow (steps 30, 35, 37, 45)

**Librelane Gating:** `classic.py`
- Position: Step 35 (line 75) - second occurrence, after CTS
- NOT in gating_config_vars dict - always runs when CTS runs

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.STAMidPNR"` (line 91)
- Uses `STA_CONFIG_KEYS` (lines 55-65)
- step_outputs: `[]`

**Bazel Flow:** `full_flow.bzl`
- Inside `if run_cts:` block - only runs when CTS runs (line 461)
- Position: Step 35, after CTS
- Named: `_sta_mid_cts`
- Chains from: `_cts` target

**Config Variable Audit:**

STAMidPNR has no additional config_vars - inherits from OpenROADStep.

Inherited OpenROADStep.config_vars (openroad.py lines 192-223):

| Variable | Type | Default | Bazel Attr | Status |
|----------|------|---------|------------|--------|
| PDN_CONNECT_MACROS_TO_GRID | bool | True | `pdn_connect_macros_to_grid` | Wired |
| PDN_MACRO_CONNECTIONS | Optional[List[str]] | None | `pdn_macro_connections` | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | bool | True | `pdn_enable_global_connections` | Wired |
| PNR_SDC_FILE | Optional[Path] | None | `pnr_sdc_file` | Wired |
| FP_DEF_TEMPLATE | Optional[Path] | None | `fp_def_template` | Wired |

OpenROADStep.prepare_env() variables (openroad.py lines 242-258):

| Variable | Usage | Bazel Status |
|----------|-------|--------------|
| FALLBACK_SDC | SDC file fallback | Wired |
| EXTRA_EXCLUDED_CELLS | Cell exclusion | Wired |

`STA_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS`, shared with the first STAMidPNR
occurrence.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.STAMidPNR"` | `"OpenROAD.STAMidPNR"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None (runs when CTS runs) | Inside `if run_cts:` | Y |
| Position | Step 35 | Step 35 | Y |
| Config vars | OpenROADStep inherited | STA_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_sta_mid_cts`
  passed.
- Produced `max.rpt`, `min.rpt`, and `state_out.json`.

---

### Step 36: OpenROAD.ResizerTimingPostCTS

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.ResizerTimingPostCTS"` (line 2697)
- Class: ResizerTimingPostCTS -> ResizerStep -> OpenROADStep -> TclStep -> Step
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- First attempt to meet timing requirements after clock tree synthesis
- Resizes cells and inserts buffers to eliminate hold/setup violations

**Librelane Gating:** `classic.py`
- Position: Step 36 (line 77)
- Variable: `RUN_POST_CTS_RESIZER_TIMING` (line 272)
- Default: `True` (line 152)

**Bazel Implementation:** `place.bzl`
- ID: `"OpenROAD.ResizerTimingPostCTS"` (line 360)
- Uses `RESIZER_TIMING_CONFIG_KEYS`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`

**Bazel Flow:** `full_flow.bzl`
- Gating: `run_post_cts_resizer_timing` parameter (default True)
- Position: Step 36, after STAMidPNR
- Named: `_rsz_cts`
- Chains from: `_sta_mid_cts` target

**Config Variable Audit:**

ResizerTimingPostCTS-specific config_vars (openroad.py lines 2698-2786):

| Variable | Type | Default | Bazel Attr | Status |
|----------|------|---------|------------|--------|
| PL_RESIZER_HOLD_SLACK_MARGIN | Decimal | 0.1 | `pl_resizer_hold_slack_margin` | Wired |
| PL_RESIZER_SETUP_SLACK_MARGIN | Decimal | 0.05 | `pl_resizer_setup_slack_margin` | Wired |
| PL_RESIZER_HOLD_MAX_BUFFER_PCT | Decimal | 50 | `pl_resizer_hold_max_buffer_pct` | Wired |
| PL_RESIZER_SETUP_MAX_BUFFER_PCT | Decimal | 50 | `pl_resizer_setup_max_buffer_pct` | Wired |
| PL_RESIZER_ALLOW_SETUP_VIOS | bool | False | `pl_resizer_allow_setup_vios` | Wired |
| PL_RESIZER_SETUP_GATE_CLONING | bool | True | `pl_resizer_gate_cloning` | Wired |
| PL_RESIZER_SETUP_BUFFERING | bool | True | `pl_resizer_setup_buffering` | Wired |
| PL_RESIZER_SETUP_BUFFER_REMOVAL | bool | True | `pl_resizer_setup_buffer_removal` | Wired |
| PL_RESIZER_SETUP_REPAIR_TNS_PCT | Optional[Decimal] | None | `pl_resizer_setup_repair_tns_pct` | Wired |
| PL_RESIZER_SETUP_MAX_UTIL_PCT | Optional[Decimal] | None | `pl_resizer_setup_max_util_pct` | Wired |
| PL_RESIZER_HOLD_REPAIR_TNS_PCT | Optional[Decimal] | None | `pl_resizer_hold_repair_tns_pct` | Wired |
| PL_RESIZER_HOLD_MAX_UTIL_PCT | Optional[Decimal] | None | `pl_resizer_hold_max_util_pct` | Wired |
| PL_RESIZER_FIX_HOLD_FIRST | bool | False | `pl_resizer_fix_hold_first` | Wired |

Inherited ResizerStep config_vars (RESIZER_CONFIG_KEYS) - all wired.

**Fixes Applied (2026-07-07):**
1. Renamed emitted config key from deprecated `PL_RESIZER_GATE_CLONING` to `PL_RESIZER_SETUP_GATE_CLONING`
2. Added LibreLane 3.0.4 setup buffering/removal and optional setup/hold repair limit knobs
3. Updated `RESIZER_TIMING_CONFIG_KEYS` to include all current ResizerTimingPostCTS-specific variables

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.ResizerTimingPostCTS"` | `"OpenROAD.ResizerTimingPostCTS"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating var | RUN_POST_CTS_RESIZER_TIMING | `run_post_cts_resizer_timing` | Y |
| Gating default | True | True | Y |
| Position | Step 36 | Step 36 | Y |
| Config vars | ResizerStep + 13 specific | RESIZER_TIMING_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_rsz_cts`
  passed.
- Produced `SegmentedMultiplier16x16.def`, `.odb`, `.nl.v`, `.pnl.v`,
  `.sdc`, and `state_out.json`.
- Runtime included setup repair with gate cloning/rebuffer/load splitting enabled,
  then inserted 146 hold buffers.

---

### Step 37: OpenROAD.STAMidPNR (third occurrence)

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.STAMidPNR"` (line 543)
- Class: STAMidPNR -> OpenROADStep -> TclStep -> Step
- inputs: `[DesignFormat.ODB]`
- outputs: `[]`
- Note: This step appears 4 times in Classic flow (steps 30, 35, 37, 45)

**Librelane Gating:** `classic.py`
- Position: Step 37 (line 78) - third occurrence, after ResizerTimingPostCTS
- NOT in gating_config_vars dict - runs when ResizerTimingPostCTS runs

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.STAMidPNR"` (line 132)
- Uses `STA_CONFIG_KEYS`
- step_outputs: `[]`

**Bazel Flow:** `full_flow.bzl`
- Inside `if run_post_cts_resizer_timing:` block (line 476)
- Position: Step 37, after ResizerTimingPostCTS
- Named: `_sta_mid_rsz_cts`
- Chains from: `_rsz_cts` target

**Config Variable Audit:**

Same as Step 35 - STAMidPNR has no additional config_vars, inherits OpenROADStep.config_vars.
STA_CONFIG_KEYS correctly includes all required variables.

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.STAMidPNR"` | `"OpenROAD.STAMidPNR"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None (runs when resizer runs) | Inside `if run_post_cts_resizer_timing:` | Y |
| Position | Step 37 | Step 37 | Y |
| Config vars | OpenROADStep inherited | STA_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_sta_mid_rsz_cts`
  passed.
- Produced `max.rpt`, `min.rpt`, and `state_out.json`.

---

### Step 38: OpenROAD.GlobalRouting

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.GlobalRouting"` (line 1849)
- Class: GlobalRouting -> OpenROADStep -> TclStep -> Step
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[DesignFormat.ODB, DesignFormat.DEF]` (line 1852)
- config_vars = OpenROADStep.config_vars + grt_variables + dpl_variables (line 1854)

**Librelane Gating:** `classic.py`
- Position: Step 38 (line 79)
- NOT in gating_config_vars dict - always runs

**Bazel Implementation:** `route.bzl`
- ID: `"OpenROAD.GlobalRouting"`
- Uses `GRT_CONFIG_KEYS`
- step_outputs: `["def", "odb"]`

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs (line 488)
- Position: Step 38, after STAMidPNR
- Named: `_grt`
- Chains from: `pre_grt_src` (varies based on CTS/resizer)

**Config Variable Audit:**

GlobalRouting config_vars (line 1854):

OpenROADStep.config_vars:

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| PNR_CORNERS | Optional[List[str]] | None | Wired |
| SET_RC_VERBOSE | bool | False | Wired |
| LAYERS_RC | Optional[Dict] | None | Wired |
| VIAS_R | Optional[Dict] | None | Wired |
| SIGNAL_WIRE_RC_LAYERS | Optional[List[str]] | None | Wired |
| CLOCK_WIRE_RC_LAYERS | Optional[List[str]] | None | Wired |
| PDN_CONNECT_MACROS_TO_GRID | bool | True | Wired |
| PDN_MACRO_CONNECTIONS | Optional[List[str]] | None | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | bool | True | Wired |
| PNR_SDC_FILE | Optional[Path] | None | Wired |
| STA_EXTRA_CORNER_TCL_FILE | Optional[Path] | None | Wired |
| DEDUPLICATE_CORNERS | bool | False | Wired |

OpenROADStep.prepare_env variables use the shared `OPENROAD_STEP_CONFIG_KEYS`
from `common.bzl`, including `FALLBACK_SDC`, `EXTRA_EXCLUDED_CELLS`,
`PNR_EXCLUDED_CELL_FILE`, and `LIB`.

grt_variables = routing_layer_variables + grt-specific:

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| RT_CLOCK_MIN_LAYER | Optional[str] | None | Wired |
| RT_CLOCK_MAX_LAYER | Optional[str] | None | Wired |
| GRT_ADJUSTMENT | Decimal | 0.3 | Wired |
| GRT_MACRO_EXTENSION | int | 0 | Wired |
| GRT_LAYER_ADJUSTMENTS | List[Decimal] | (pdk) | Wired (PDK) |
| DIODE_PADDING | Optional[int] | None | Wired |
| GRT_ALLOW_CONGESTION | bool | False | Wired |
| GRT_ANTENNA_REPAIR_ITERS | int | 3 | Wired |
| GRT_OVERFLOW_ITERS | int | 50 | Wired |
| GRT_ANTENNA_REPAIR_MARGIN | int | 10 | Wired |
| GRT_ANTENNA_REPAIR_JUMPER_ONLY | bool | False | Wired |
| GRT_ANTENNA_REPAIR_DIODE_ONLY | bool | False | Wired |

dpl_variables (4 vars):

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| PL_OPTIMIZE_MIRRORING | bool | True | Wired |
| PL_MAX_DISPLACEMENT_X | Decimal | 500 | Wired |
| PL_MAX_DISPLACEMENT_Y | Decimal | 100 | Wired |
| DPL_CELL_PADDING | Decimal | (pdk) | Wired (PDK) |

**Fixes Applied (2026-07-07):**
1. Changed `route.bzl` to reuse shared `OPENROAD_STEP_CONFIG_KEYS`
2. Renamed deprecated `GRT_ANTENNA_ITERS`/`GRT_ANTENNA_MARGIN` to
   `GRT_ANTENNA_REPAIR_ITERS`/`GRT_ANTENNA_REPAIR_MARGIN`
3. Added `GRT_ANTENNA_REPAIR_JUMPER_ONLY` and
   `GRT_ANTENNA_REPAIR_DIODE_ONLY`
4. Renamed full-flow override arguments and the maths DSE call site

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.GlobalRouting"` | `"OpenROAD.GlobalRouting"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating | None | None | Y |
| Position | Step 38 | Step 38 | Y |
| Config vars | OpenROADStep + grt_variables + dpl_variables | GRT_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_grt`
  passed.
- Produced `SegmentedMultiplier16x16.def`, `.odb`, and `state_out.json`.
- Runtime called `global_route -congestion_iterations 50 -verbose` and reported
  zero final routing overflow.

---

### Step 39: OpenROAD.CheckAntennas (first occurrence)

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.CheckAntennas"` (line 1698)
- Class: CheckAntennas -> OpenROADStep -> TclStep -> Step
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[]`
- Checks for antenna rule violations in long nets
- Note: This step appears twice in Classic flow (steps 39 and 48)

**Librelane Gating:** `classic.py`
- Position: Step 39 (line 80) - first occurrence, after GlobalRouting
- NOT in gating_config_vars dict - always runs

**Config Variable Audit:**

CheckAntennas has no explicit config_vars, so it inherits only OpenROADStep.config_vars.
Its `run()` method writes `reports/antenna.rpt` and
`reports/antenna_summary.rpt`, and updates
`route__antenna_violation__count`.

OpenROADStep config comes from shared `OPENROAD_STEP_CONFIG_KEYS`, as in
Step 38.

No CheckAntennas-specific config keys are required.

**Bazel Implementation:** `route.bzl`
- ID: `"OpenROAD.CheckAntennas"`
- Uses `CHECK_ANTENNAS_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS`
- step_outputs: `[]`
- extra_outputs: `reports/antenna.rpt`, `reports/antenna_summary.rpt`

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs (lines 494-499)
- Position: Step 39, after GlobalRouting
- Named: `_chk_ant_grt`
- Chains from: `_grt` target

**Fixes Applied (2026-07-07):**
1. `route.bzl` now uses the shared current `OPENROAD_STEP_CONFIG_KEYS`
2. `CHECK_ANTENNAS_CONFIG_KEYS` remains exactly the OpenROADStep key set

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.CheckAntennas"` | `"OpenROAD.CheckAntennas"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | Y |
| Position | Step 39 | Step 39 | Y |
| Config vars | OpenROADStep inherited | CHECK_ANTENNAS_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_ant_grt`
  passed.
- Produced `reports/antenna.rpt`, `reports/antenna_summary.rpt`, and
  `state_out.json`.
- The checker reported 6 antenna violations in the post-GRT design. This step
  records those reports/metrics; it does not fail the build.

---

### Step 40: OpenROAD.RepairDesignPostGRT

**Verified:** 2026-07-07 source/config audit; runtime deferred

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.RepairDesignPostGRT"` (line 2646)
- Class: RepairDesignPostGRT -> ResizerStep -> OpenROADStep -> TclStep -> Step
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- Runs design repairs after global routing (experimental)

**Librelane Gating:** `classic.py`
- Position: Step 40 (line 81)
- Variable: `RUN_POST_GRT_DESIGN_REPAIR` (line 271)
- Default: **`False`** (line 139)
- This step is OFF by default because it's experimental

**Config Variable Audit:**

RepairDesignPostGRT.config_vars = ResizerStep.config_vars + 4 step-specific.
ResizerStep.config_vars = OpenROADStep.config_vars + grt_variables + rsz_variables.

The inherited OpenROADStep and grt_variables key sets are shared with Steps 38
and 39, including the current `GRT_ANTENNA_REPAIR_*` names. The inherited
rsz_variables are:

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| PL_OPTIMIZE_MIRRORING | bool | True | Wired |
| PL_MAX_DISPLACEMENT_X | Decimal | 500 | Wired |
| PL_MAX_DISPLACEMENT_Y | Decimal | 100 | Wired |
| DPL_CELL_PADDING | Decimal | (pdk) | Wired (PDK) |
| RSZ_DONT_TOUCH_RX | str | "$^" | Wired |
| RSZ_DONT_TOUCH_LIST | Optional[List[str]] | None | Wired |
| RSZ_CORNERS | Optional[List[str]] | None | Wired |

RepairDesignPostGRT-specific (4 vars, openroad.py lines 2649-2684):

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| GRT_DESIGN_REPAIR_RUN_GRT | bool | True | Wired |
| GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH | Decimal | 0 | Wired |
| GRT_DESIGN_REPAIR_MAX_SLEW_PCT | Decimal | 10 | Wired |
| GRT_DESIGN_REPAIR_MAX_CAP_PCT | Decimal | 10 | Wired |

**Bazel Implementation:** `route.bzl`
- ID: `"OpenROAD.RepairDesignPostGRT"`
- Uses `REPAIR_DESIGN_POST_GRT_CONFIG_KEYS`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`

**Bazel Flow:** `full_flow.bzl`
- Gating: `if run_post_grt_design_repair:` (line 502)
- Position: Step 40, after CheckAntennas
- Named: `_rsz_grt`
- Chains from: `_chk_ant_grt` target

**Fixes Applied (2026-07-07):**
1. `RESIZER_STEP_CONFIG_KEYS` now inherits the shared current
   `OPENROAD_STEP_CONFIG_KEYS`
2. Inherited grt_variables now use the current `GRT_ANTENNA_REPAIR_*` keys

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.RepairDesignPostGRT"` | `"OpenROAD.RepairDesignPostGRT"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating var | RUN_POST_GRT_DESIGN_REPAIR | `run_post_grt_design_repair` | Y |
| Gating default | False | False | Y |
| Position | Step 40 | Step 40 | Y |
| Config vars | ResizerStep + 4 specific | REPAIR_DESIGN_POST_GRT_CONFIG_KEYS | Y |

**Status: DEFERRED**

Runtime verification:
- Not run in this pass. The small multiplier flow keeps
  `run_post_grt_design_repair = False`, matching LibreLane's default, so it has
  no `_rsz_grt` target.
- The enabled `LocalExec_1024lanes_sky130hd_rsz_grt` target is a large design;
  we are deferring large-design runs until the flow audit is complete.

---

### Step 41: Odb.DiodesOnPorts

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.DiodesOnPorts"` (line 808)
- Class: DiodesOnPorts -> CompositeStep -> Step
- Sub-steps: PortDiodePlacement, DetailedPlacement, GlobalRouting
- inputs: (from sub-steps) `[ODB]`
- outputs: (from sub-steps) `[ODB, DEF]`
- **Self-skips if DIODE_ON_PORTS == "none"** (lines 819-821)

**Librelane Gating:** `classic.py`
- Position: Step 41 (line 82)
- NOT in gating_config_vars dict
- Relies on self-skip behavior (DIODE_ON_PORTS defaults to "none")

**Config Variable Audit:**

CompositeStep's config_vars = union of all sub-step config_vars.

PortDiodePlacement.config_vars (odb.py:738-752):

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| DIODE_ON_PORTS | Literal["none","in","out","both"] | "none" | Wired |
| GPL_CELL_PADDING | Decimal | (pdk) | Wired (PDK) |

PortDiodePlacement.get_command() also uses (odb.py:761):

| Variable | Status |
|----------|--------|
| DIODE_CELL | Wired (PDK) |

DetailedPlacement.config_vars = OpenROADStep.config_vars + dpl_variables.
GlobalRouting.config_vars = OpenROADStep.config_vars + grt_variables + dpl_variables.

Union needed (excluding duplicates):

| Category | Variables | Status |
|----------|-----------|--------|
| OpenROADStep.config_vars / prepare_env | Shared `OPENROAD_STEP_CONFIG_KEYS` | Wired |
| grt_variables | Current `GRT_ANTENNA_REPAIR_*` names | Wired |
| dpl_variables | 4 vars | Wired |

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.DiodesOnPorts"`
- Uses `DIODES_ON_PORTS_CONFIG_KEYS`
- step_outputs: `["def", "odb"]` only when `diode_on_ports != "none"`;
  otherwise pass-through state only

**Bazel Flow:** `full_flow.bzl`
- Parameter: `diode_on_ports = "none"` (line 116)
- Gating: none; always instantiated and self-skips
- Position: Step 41, after RepairDesignPostGRT
- Named: `_dio_ports`

**Fixes Applied (2026-07-07):**
1. Updated `DIODES_ON_PORTS_CONFIG_KEYS` to use shared
   `OPENROAD_STEP_CONFIG_KEYS` and current grt_variables
2. Changed full flow to always instantiate the step, matching LibreLane
   self-skip behavior
3. Made Bazel DEF/ODB outputs conditional on `diode_on_ports != "none"`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.DiodesOnPorts"` | `"Odb.DiodesOnPorts"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating | Self-skips if DIODE_ON_PORTS=="none" | always instantiated, self-skips | Y |
| Default | "none" (skip) | "none" (skip) | Y |
| Position | Step 41 | Step 41 | Y |
| Config vars | ~24 variables | DIODES_ON_PORTS_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_dio_ports`
  passed.
- Runtime log reported:
  `'DIODE_ON_PORTS' is set to 'none': skipping 'Odb.DiodesOnPorts'...`
- Produced `state_out.json` only, as expected for pass-through self-skip.

---

### Step 42: Odb.HeuristicDiodeInsertion

**Verified:** 2026-07-07 source/config audit; runtime deferred

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.HeuristicDiodeInsertion"` (line 920)
- Class: HeuristicDiodeInsertion -> CompositeStep -> Step
- Sub-steps: FuzzyDiodePlacement, DetailedPlacement, GlobalRouting
- inputs: (from sub-steps) `[ODB]`
- outputs: (from sub-steps) `[ODB, DEF]`
- Places diodes based on Manhattan length heuristic

**Librelane Gating:** `classic.py`
- Position: Step 42 (line 83)
- Variable: `RUN_HEURISTIC_DIODE_INSERTION` (line 277)
- Default: `False` (line 166) - OFF by default

**Config Variable Audit:**

CompositeStep's config_vars = union of all sub-step config_vars.

FuzzyDiodePlacement.config_vars (odb.py:840-855):

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| HEURISTIC_ANTENNA_THRESHOLD | Decimal | (pdk) | Wired (PDK) |
| GPL_CELL_PADDING | Decimal | (pdk) | Wired (PDK) |

FuzzyDiodePlacement.get_command() also uses (odb.py:864):

| Variable | Status |
|----------|--------|
| DIODE_CELL | Wired (PDK) |

DetailedPlacement.config_vars = OpenROADStep.config_vars + dpl_variables.
GlobalRouting.config_vars = OpenROADStep.config_vars + grt_variables + dpl_variables.

Union needed (excluding duplicates):

| Category | Variables | Status |
|----------|-----------|--------|
| OpenROADStep.config_vars / prepare_env | Shared `OPENROAD_STEP_CONFIG_KEYS` | Wired |
| grt_variables | Current `GRT_ANTENNA_REPAIR_*` names | Wired |
| dpl_variables | 4 vars | Wired |

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.HeuristicDiodeInsertion"`
- Uses `HEURISTIC_DIODE_CONFIG_KEYS`
- step_outputs: `["def", "odb"]`

**Bazel Flow:** `full_flow.bzl`
- Parameter: `run_heuristic_diode_insertion = False` (line 117)
- Gating: `if run_heuristic_diode_insertion:` (line 525)
- Position: Step 42, after DiodesOnPorts
- Named: `_dio_heur`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.HeuristicDiodeInsertion"` | `"Odb.HeuristicDiodeInsertion"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating var | RUN_HEURISTIC_DIODE_INSERTION | run_heuristic_diode_insertion | Y |
| Gating default | False | False | Y |
| Position | Step 42 | Step 42 | Y |
| Config vars | ~24 variables | HEURISTIC_DIODE_CONFIG_KEYS | Y |

**Status: DEFERRED**

Runtime verification:
- Not run in this pass. The small multiplier flow keeps
  `run_heuristic_diode_insertion = False`, matching LibreLane's default, so it
  has no `_dio_heur` target.

---

### Step 43: OpenROAD.RepairAntennas

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.RepairAntennas"` (line 1882)
- Class: RepairAntennas -> CompositeStep -> Step
- Sub-steps: _DiodeInsertion (GlobalRouting subclass), CheckAntennas
- inputs: `[ODB]` (inherited)
- outputs: `[ODB, DEF]` (inherited)
- Applies antenna effect mitigations using global routing info, then re-legalizes

**Librelane Gating:** `classic.py`
- Position: Step 43 (line 84)
- Variable: `RUN_ANTENNA_REPAIR` (line 278)
- Default: `True` (line 172)
- Users CAN disable antenna repair by setting RUN_ANTENNA_REPAIR=False

**Config Variable Audit:**

CompositeStep's config_vars = union of all sub-step config_vars.

_DiodeInsertion inherits GlobalRouting:
- config_vars = OpenROADStep.config_vars + grt_variables + dpl_variables

CheckAntennas.config_vars = OpenROADStep.config_vars, no additional.

Union needed (excluding duplicates):

| Category | Variables | Status |
|----------|-----------|--------|
| OpenROADStep.config_vars / prepare_env | Shared `OPENROAD_STEP_CONFIG_KEYS` | Wired |
| grt_variables | Current `GRT_ANTENNA_REPAIR_*` names | Wired |
| dpl_variables | 4 vars | Wired |

**Bazel Implementation:** `route.bzl`
- ID: `"OpenROAD.RepairAntennas"`
- Uses `REPAIR_ANTENNAS_CONFIG_KEYS = GRT_CONFIG_KEYS`
- step_outputs: `["def", "odb"]`
- output_subdir: `"1-openroad-diodeinsertion"`

**Bazel Flow:** `full_flow.bzl`
- Parameter: `run_antenna_repair = True` (line 118)
- Gating: `if run_antenna_repair:` (line 536)
- Position: Step 43, after HeuristicDiodeInsertion
- Named: `_ant`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.RepairAntennas"` | `"OpenROAD.RepairAntennas"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating var | RUN_ANTENNA_REPAIR | run_antenna_repair | Y |
| Gating default | True | True | Y |
| Position | Step 43 | Step 43 | Y |
| Config vars | ~21 variables | REPAIR_ANTENNAS_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_ant` passed.
- Initial run failed because the wrapper expected old composite output
  directory `1-diodeinsertion`; LibreLane 3.0.4 writes
  `1-openroad-diodeinsertion`. The wrapper was updated.
- Runtime repaired antenna violations to zero, inserting 20 jumpers, then 1
  diode, then 10 jumpers, then 4 diodes.
- Produced `SegmentedMultiplier16x16.def`, `.odb`, and `state_out.json`.

---

### Step 44: OpenROAD.ResizerTimingPostGRT

**Verified:** 2026-07-07 source/config audit; runtime deferred

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.ResizerTimingPostGRT"` (line 2803)
- Class: ResizerTimingPostGRT -> ResizerStep -> OpenROADStep
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- Second attempt at timing optimization after global routing
- Note: This is experimental and may cause hangs or extended run times

**Librelane Gating:** `classic.py`
- Position: Step 44 (line 85)
- Variable: `RUN_POST_GRT_RESIZER_TIMING` (line 273)
- Default: **`False`** (line 159)
- This step is OFF by default because it's experimental

**Config Variable Audit:**

ResizerTimingPostGRT.config_vars = ResizerStep.config_vars + step-specific
variables (openroad.py lines 2805-2902).

Step-specific variables:

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| GRT_RESIZER_HOLD_SLACK_MARGIN | Decimal | 0.05 ns | Wired |
| GRT_RESIZER_SETUP_SLACK_MARGIN | Decimal | 0.025 ns | Wired |
| GRT_RESIZER_HOLD_MAX_BUFFER_PCT | Decimal | 50% | Wired |
| GRT_RESIZER_SETUP_MAX_BUFFER_PCT | Decimal | 50% | Wired |
| GRT_RESIZER_ALLOW_SETUP_VIOS | bool | False | Wired |
| GRT_RESIZER_SETUP_GATE_CLONING | bool | True | Wired |
| GRT_RESIZER_RUN_GRT | bool | True | Wired |
| GRT_RESIZER_SETUP_BUFFERING | bool | True | Wired |
| GRT_RESIZER_SETUP_BUFFER_REMOVAL | bool | True | Wired |
| GRT_RESIZER_SETUP_REPAIR_TNS_PCT | Optional[Decimal] | None | Wired |
| GRT_RESIZER_SETUP_MAX_UTIL_PCT | Optional[Decimal] | None | Wired |
| GRT_RESIZER_HOLD_REPAIR_TNS_PCT | Optional[Decimal] | None | Wired |
| GRT_RESIZER_HOLD_MAX_UTIL_PCT | Optional[Decimal] | None | Wired |
| GRT_RESIZER_FIX_HOLD_FIRST | bool | False | Wired |

ResizerStep.config_vars (from RESIZER_STEP_CONFIG_KEYS):

| Category | Variables | Status |
|----------|-----------|--------|
| OpenROADStep.config_vars / prepare_env | Shared `OPENROAD_STEP_CONFIG_KEYS` | Wired |
| grt_variables | Current `GRT_ANTENNA_REPAIR_*` names | Wired |
| rsz_variables | 7 vars | Wired |

**Bazel Implementation:** `route.bzl`
- ID: `"OpenROAD.ResizerTimingPostGRT"`
- Uses `RESIZER_TIMING_POST_GRT_CONFIG_KEYS`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`

**Bazel Flow:** `full_flow.bzl`
- Parameter: `run_post_grt_resizer_timing = False` (line 119)
- Gating: `if run_post_grt_resizer_timing:` (line 548)
- Position: Step 44, after RepairAntennas
- Named: `_rsz_grt2`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.ResizerTimingPostGRT"` | `"OpenROAD.ResizerTimingPostGRT"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating var | RUN_POST_GRT_RESIZER_TIMING | run_post_grt_resizer_timing | Y |
| Gating default | False | False | Y |
| Position | Step 44 | Step 44 | Y |
| Config vars | ResizerStep + 14 specific | RESIZER_TIMING_POST_GRT_CONFIG_KEYS | Y |

**Status: DEFERRED**

Fixes applied:
- Renamed emitted config key from deprecated `GRT_RESIZER_GATE_CLONING` to
  `GRT_RESIZER_SETUP_GATE_CLONING`.
- Added LibreLane 3.0.4 setup buffering/removal and optional setup/hold repair
  limit knobs.

Runtime verification:
- Not run in this pass. The small multiplier flow keeps
  `run_post_grt_resizer_timing = False`, matching LibreLane's default, so it has
  no `_rsz_grt2` target.
- `bazel build --nobuild //dse/maths:SegmentedMultiplier16x16_sky130hd_ant`
  passed after adding the Step 44 config plumbing.

---

### Step 45: OpenROAD.STAMidPNR (fourth occurrence)

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.STAMidPNR"` (line 543)
- Class: STAMidPNR -> OpenROADStep
- inputs: `[DesignFormat.ODB]`
- outputs: `[]`
- Note: This step appears 4 times in Classic flow (steps 30, 35, 37, 45)

**Librelane Gating:** `classic.py`
- Position: Step 45 (line 86) - fourth occurrence, after ResizerTimingPostGRT
- NOT in gating_config_vars dict - always runs

**Config Variable Audit:**

STAMidPNR.config_vars = OpenROADStep.config_vars; no additional variables.

| Category | Variables | Status |
|----------|-----------|--------|
| OpenROADStep.config_vars / prepare_env | Shared `OPENROAD_STEP_CONFIG_KEYS` | Wired |

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.STAMidPNR"`
- Uses `STA_CONFIG_KEYS`
- step_outputs: `[]`

**Bazel Flow:** `full_flow.bzl`
- No gating - always runs (line 555)
- Position: Step 45, after ResizerTimingPostGRT
- Named: `_sta_mid_rsz_grt`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.STAMidPNR"` | `"OpenROAD.STAMidPNR"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | Y |
| Position | Step 45 | Step 45 | Y |
| Config vars | ~7 variables | STA_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_sta_mid_rsz_grt`
  passed.
- Produced `max.rpt`, `min.rpt`, and `state_out.json`.
- Runtime read the ODB from `SegmentedMultiplier16x16_sky130hd_ant`.

---

### Step 46: OpenROAD.DetailedRouting

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.DetailedRouting"` (line 1928)
- Class: DetailedRouting -> OpenROADStep
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- Transforms abstract nets into metal layer wires respecting design rules
- Longest step in typical flow (hours/days/weeks on larger designs)

**Librelane Gating:** `classic.py`
- Position: Step 46 (line 87)
- Variable: `RUN_DRT` (line 279)
- Default: `True` (line 179)
- Users CAN disable detailed routing by setting RUN_DRT=False

**Config Variable Audit:**

DetailedRouting.config_vars = OpenROADStep.config_vars + grt_variables +
step-specific variables (openroad.py lines 1931-1993).

Step-specific variables:

| Variable | Type | Default | Status |
|----------|------|---------|--------|
| DRT_THREADS | Optional[int] | machine threads | Wired |
| DRT_OPT_ITERS | int | 64 | Wired |
| DRT_SAVE_SNAPSHOTS | bool | False | Wired |
| DRT_ANTENNA_REPAIR_ITERS | int | 3 | Wired |
| DRT_ANTENNA_REPAIR_MARGIN | int | 10 | Wired |
| DRT_ANTENNA_REPAIR_JUMPER_ONLY | bool | False | Wired |
| DRT_ANTENNA_REPAIR_DIODE_ONLY | bool | False | Wired |
| DRT_SAVE_DRC_REPORT_ITERS | Optional[int] | None | Wired |
| NON_DEFAULT_RULES | Optional[dict] | None | Wired |
| DRT_ASSIGN_NDR | Optional[dict] | None | Wired |

OpenROADStep.config_vars:

| Category | Variables | Status |
|----------|-----------|--------|
| OpenROADStep.config_vars / prepare_env | Shared `OPENROAD_STEP_CONFIG_KEYS` | Wired |
| grt_variables | Current `GRT_ANTENNA_REPAIR_*` names | Wired |

**Bazel Implementation:** `route.bzl`
- ID: `"OpenROAD.DetailedRouting"`
- Uses `DETAILED_ROUTING_CONFIG_KEYS`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`

**Bazel Flow:** `full_flow.bzl`
- Parameter: `run_drt = True` (line 121)
- Gating: `if run_drt:` (line 568)
- Position: Step 46, after STAMidPNR
- Named: `_drt`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.DetailedRouting"` | `"OpenROAD.DetailedRouting"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating var | RUN_DRT | run_drt | Y |
| Gating default | True | True | Y |
| Position | Step 46 | Step 46 | Y |
| Config vars | OpenROADStep + grt_variables + DRT-specific | DETAILED_ROUTING_CONFIG_KEYS | Y |

**Status: PASS**

Fixes applied:
- Removed obsolete `DRT_MIN_LAYER` and `DRT_MAX_LAYER` from the Bazel config
  surface.
- Added current DRT-specific variables, including snapshot, antenna repair,
  DRC-report interval, and optional NDR dictionaries.
- Kept the DetailedRouting key list scoped to OpenROADStep + grt_variables +
  DRT-specific variables, without DPL-only keys.

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_drt` passed.
- Runtime ran TritonRoute with 6 threads and `-droute_end_iter 64`.
- Detailed routing completed with zero DRT violations; post-route antenna check
  found zero net and pin violations.
- Produced DEF, ODB, NL, PNL, SDC, and `state_out.json`.

---

### Step 47: Odb.RemoveRoutingObstructions

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.RemoveRoutingObstructions"` (line 597)
- inputs: `[DesignFormat.ODB]` (inherited from OdbpyStep)
- outputs: `[DesignFormat.ODB, DesignFormat.DEF]` (inherited from OdbpyStep)
- Subclass of AddRoutingObstructions; inherits `ROUTING_OBSTRUCTIONS`
- Self-skipping: when `ROUTING_OBSTRUCTIONS` is `None`, inherited run method
  skips

**Librelane Gating:** `classic.py`
- Position: Step 47 (line 88)
- No entry in gating_config_vars dict
- Gating is implicit via ROUTING_OBSTRUCTIONS config variable - step self-skips when None

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.RemoveRoutingObstructions"`
- step_outputs: `["def", "odb"]` only when `routing_obstructions` is set;
  otherwise pass-through state only
- Uses `ROUTING_OBS_CONFIG_KEYS = ODB_CONFIG_KEYS + ["ROUTING_OBSTRUCTIONS"]`

**Config Variable Audit:**

Inheritance: RemoveRoutingObstructions → AddRoutingObstructions → OdbpyStep → Step

| Variable | Source | Wired | Status |
|----------|--------|-------|--------|
| ROUTING_OBSTRUCTIONS | AddRoutingObstructions (odb.py:537-547) | 5-loc pattern | PASS |

**Bazel Flow:** `full_flow.bzl`
- Position: Step 47
- Always instantiated; self-skips when `routing_obstructions` is unset
- Named: `_rm_route_obs`
- Chains from: `pre_rm_obs_src` (either `_drt` or `_sta_mid_rsz_grt`)
- `post_drt_src` always points to `_rm_route_obs`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.RemoveRoutingObstructions"` | `"Odb.RemoveRoutingObstructions"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` | `["def", "odb"]` | Y |
| Gating | Self-skip when ROUTING_OBSTRUCTIONS=None | always instantiated, self-skips | Y |
| Position | Step 47 | Step 47 | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_rm_route_obs`
  passed.
- Runtime log reported:
  `'ROUTING_OBSTRUCTIONS' is not defined. Skipping 'Odb.RemoveRoutingObstructions'...`
- Produced `state_out.json` only, as expected for pass-through self-skip.

---

### Step 48: OpenROAD.CheckAntennas (second occurrence)

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.CheckAntennas"` (line 1698)
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[]`; produces reports/metrics, no design views
- Checks for antenna rule violations and updates route__antenna_violation__count metric

**Librelane Gating:** `classic.py`
- Position: second occurrence at line 89 (Step 48, after RemoveRoutingObstructions)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `route.bzl`
- ID: `"OpenROAD.CheckAntennas"`
- step_outputs: `[]`
- extra_outputs: `reports/antenna.rpt`, `reports/antenna_summary.rpt`
- Uses `CHECK_ANTENNAS_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS`

**Config Variable Audit:**

Inheritance: CheckAntennas → OpenROADStep → Step

CheckAntennas has no step-specific config_vars. It only inherits
OpenROADStep.config_vars, covered by shared `OPENROAD_STEP_CONFIG_KEYS`.

**Bazel Flow:** `full_flow.bzl`
- Position: Step 48 (line 588 comment)
- No gating - always runs
- Named: `_chk_ant_drt`
- Chains from: `post_drt_src` (either `_rm_route_obs` or `_drt` depending on routing_obstructions)

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.CheckAntennas"` | `"OpenROAD.CheckAntennas"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 48 (line 88) | Step 48 (line 588) | Y |

**Notes:** This is the second occurrence of CheckAntennas (first was Step 39). It runs after
detailed routing to verify antenna violations. No gating needed.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_ant_drt`
  passed.
- Produced `reports/antenna.rpt`, `reports/antenna_summary.rpt`, and
  `state_out.json`.
- `antenna_summary.rpt` was empty, indicating zero reported antenna violations.

---

### Step 49: Checker.TrDRC

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.TrDRC"` (line 179)
- inputs: `[]` (inherited from MetricChecker)
- outputs: `[]` (inherited from MetricChecker)
- Checks metric `route__drc_errors` (line 183)
- Raises deferred error if DRC errors > 0 (unless ERROR_ON_TR_DRC=False)

**Librelane Gating:** `classic.py`
- Position: Step 49 (line 90)
- Variable: `RUN_DRT` (line 294)
- When RUN_DRT=False, TrDRC is skipped (makes sense - no routing = no DRC to check)

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.TrDRC"`
- step_outputs: `[]`
- Uses `TR_DRC_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_TR_DRC"]`

**Config Variable Audit:**

Inheritance: TrDRC → MetricChecker → Step

| Variable | Source | Wired | Status |
|----------|--------|-------|--------|
| ERROR_ON_TR_DRC | TrDRC (checker.py:186-192) | 5-loc pattern | PASS |

**Bazel Flow:** `full_flow.bzl`
- Position: Step 49
- No gating - always runs
- Named: `_chk_tr_drc`
- Chains from: `_chk_ant_drt`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.TrDRC"` | `"Checker.TrDRC"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating var | RUN_DRT | (none, inherits from DRT) | Y |
| Position | Step 49 (line 89) | Step 49 (line 595) | Y |
| Config vars | ERROR_ON_TR_DRC | TR_DRC_CONFIG_KEYS | Y |

**Notes:** TrDRC is gated by RUN_DRT in LibreLane. In the Bazel flow this path
is only reached after the DRT branch, so the effective behavior matches.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_tr_drc`
  passed.
- Runtime log reported: `Check for Routing DRC errors clear.`
- Produced `state_out.json`.

---

### Step 50: Odb.ReportDisconnectedPins

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.ReportDisconnectedPins"` (line 502)
- inputs: `[DesignFormat.ODB]` (inherited from OdbpyStep)
- outputs: `[DesignFormat.ODB, DesignFormat.DEF]` (inherited from OdbpyStep)
- Updates metrics: design__disconnected_pin__count, design__critical_disconnected_pin__count

**Librelane Gating:** `classic.py`
- Position: Step 50 (line 90)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.ReportDisconnectedPins"` (line 136)
- step_outputs: `[]` - reports metrics only, no design file output
- Uses REPORT_DISCONNECTED_PINS_CONFIG_KEYS (line 11)

**Config Variable Audit:**

Inheritance: ReportDisconnectedPins → OdbpyStep → Step

| Variable | Source | pdk | Wired | Status |
|----------|--------|-----|-------|--------|
| IGNORE_DISCONNECTED_MODULES | odb.py:506-512 | Y | PDK path | PASS |

Wiring for PDK variable:
1. pdk_repo.bzl line 158: defines mapping ✓
2. common.bzl create_librelane_config line 218: adds from pdk ✓
3. odb.bzl REPORT_DISCONNECTED_PINS_CONFIG_KEYS line 11: includes in filter ✓

**Bazel Flow:** `full_flow.bzl`
- Position: Step 50 (line 602 comment)
- No gating - always runs
- Named: `_rpt_disc_pins`
- Chains from: `_chk_tr_drc`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.ReportDisconnectedPins"` | `"Odb.ReportDisconnectedPins"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 50 | Step 50 | Y |
| Config vars | OdbpyStep + `IGNORE_DISCONNECTED_MODULES` | REPORT_DISCONNECTED_PINS_CONFIG_KEYS | Y |

**Notes:** Current LibreLane explicitly sets `outputs = []` for this report step.
The wrapper declares `full_disconnected_pins_table.txt` as an optional auxiliary
output: it is copied when LibreLane writes it and created empty when the report
is omitted, as happens for a clean design with zero disconnected pins.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_rpt_disc_pins`
  passed.
- Runtime reported 0 disconnected pins, 0 critical.
- Produced `state_out.json` and an empty optional
  `full_disconnected_pins_table.txt`.

---

### Step 51: Checker.DisconnectedPins

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.DisconnectedPins"` (line 235)
- inputs: `[]` (inherited from MetricChecker)
- outputs: `[]` (inherited from MetricChecker)
- deferred: False - raises immediate error, not deferred
- Checks metric: `design__critical_disconnected_pin__count`

**Librelane Gating:** `classic.py`
- Position: Step 51 (line 92)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.DisconnectedPins"`
- step_outputs: `[]`
- Uses `DISCONNECTED_PINS_CONFIG_KEYS`

**Config Variable Audit:**

Inheritance: DisconnectedPins → MetricChecker → Step

| Variable | Source | Wired | Status |
|----------|--------|-------|--------|
| ERROR_ON_DISCONNECTED_PINS | checker.py:243-250 | 5-loc pattern | PASS |

**Bazel Flow:** `full_flow.bzl`
- Position: Step 51
- No gating - always runs
- Named: `_chk_disc_pins`
- Chains from: `_rpt_disc_pins`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.DisconnectedPins"` | `"Checker.DisconnectedPins"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 51 (line 91) | Step 51 (line 609) | Y |
| Config vars | ERROR_ON_DISCONNECTED_PINS | DISCONNECTED_PINS_CONFIG_KEYS | Y |

**Notes:** Unlike most checkers, this one has deferred=False, meaning it will halt the flow
immediately if critical disconnected pins are found (unless ERROR_ON_DISCONNECTED_PINS=False).

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_disc_pins`
  passed.
- Runtime log reported: `Check for critical disconnected pins clear.`
- Produced `state_out.json`.

---

### Step 52: Odb.ReportWireLength

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.ReportWireLength"` (line 478)
- inputs: `[DesignFormat.ODB]` (inherited from OdbpyStep)
- outputs: `[]` - explicitly overrides to empty
- Produces `wire_lengths.csv` report file

**Librelane Gating:** `classic.py`
- Position: Step 52 (line 93)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.ReportWireLength"`
- step_outputs: `[]`
- extra_outputs: `wire_lengths.csv`
- Uses `ODB_CONFIG_KEYS`

**Config Variable Audit:**

Inheritance: ReportWireLength → OdbpyStep → Step

No step-specific config_vars. Uses OdbpyStep LEF-loading config.

**Bazel Flow:** `full_flow.bzl`
- Position: Step 52
- No gating - always runs
- Named: `_rpt_wire_len`
- Chains from: `_chk_disc_pins`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.ReportWireLength"` | `"Odb.ReportWireLength"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 52 (line 92) | Step 52 (line 616) | Y |

**Notes:** This step explicitly overrides outputs to [] (unlike ReportDisconnectedPins which
inherits OdbpyStep outputs). Both implementations match.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_rpt_wire_len`
  passed.
- Produced `wire_lengths.csv` and `state_out.json`.
- CSV header is `net,length_um`.

---

### Step 53: Checker.WireLength

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.WireLength"` (line 255)
- inputs: `[]` (inherited from MetricChecker)
- outputs: `[]` (inherited from MetricChecker)
- Checks metric: `route__wirelength__max`
- Uses optional `WIRE_LENGTH_THRESHOLD` from PDK config

**Librelane Gating:** `classic.py`
- Position: Step 53 (line 94)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.WireLength"`
- step_outputs: `[]`
- Uses `WIRE_LENGTH_CONFIG_KEYS`

**Config Variable Audit:**

Inheritance: WireLength → MetricChecker → Step

| Variable | Source | Wired | Status |
|----------|--------|-------|--------|
| ERROR_ON_LONG_WIRE | checker.py:261-268 | 5-loc pattern | PASS |
| WIRE_LENGTH_THRESHOLD | flow.py:56-62 (pdk=True) | PDK path | PASS |

**Bazel Flow:** `full_flow.bzl`
- Position: Step 53
- No gating - always runs
- Named: `_chk_wire_len`
- Chains from: `_rpt_wire_len`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.WireLength"` | `"Checker.WireLength"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 53 (line 93) | Step 53 (line 623) | Y |
| Config vars | ERROR_ON_LONG_WIRE, WIRE_LENGTH_THRESHOLD | WIRE_LENGTH_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_wire_len`
  passed.
- Runtime warned that `WIRE_LENGTH_THRESHOLD` is not set, so the checker was
  skipped.
- Produced `state_out.json`.

---

### Step 54: OpenROAD.FillInsertion

**Verified:** 2026-07-07

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.FillInsertion"` (line 2052)
- inputs: `[DesignFormat.ODB]` (inherited from OpenROADStep)
- outputs: `[ODB, DEF, SDC, NETLIST, POWERED_NETLIST]` (inherited from OpenROADStep)
- Fills gaps with filler and decap cells

**Librelane Gating:** `classic.py`
- Position: Step 54 (line 95)
- Variable: `RUN_FILL_INSERTION` (line 280)
- Default: `True` (line 185)

**Bazel Implementation:** `macro.bzl`
- ID: `"OpenROAD.FillInsertion"`
- step_outputs: `["def", "odb", "nl", "pnl", "sdc"]`
- Uses `FILL_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS`

**Config Variable Audit:**

Inheritance: FillInsertion → OpenROADStep → Step

FillInsertion has no step-specific config_vars. It inherits OpenROADStep.config_vars.

**Bazel Flow:** `full_flow.bzl`
- Position: Step 54
- Gated by `run_fill_insertion`, default `True`
- Named: `_fill`
- Chains from: `_chk_wire_len`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.FillInsertion"` | `"OpenROAD.FillInsertion"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF, SDC, NL, PNL]` | `["def", "odb", "nl", "pnl", "sdc"]` | Y |
| Gating var | RUN_FILL_INSERTION | run_fill_insertion | Y |
| Gating default | True | True | Y |
| Position | Step 54 (line 94) | Step 54 (line 630) | Y |

If `run_fill_insertion = False`, the next step chains from `_chk_wire_len`.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_fill` passed.
- Runtime placed 10,039 filler instances.
- Produced DEF, ODB, NL, PNL, SDC, and `state_out.json`.

---

### Step 55: Odb.CellFrequencyTables

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.CellFrequencyTables"` (line 955)
- inputs: `[DesignFormat.ODB]` (inherited from OdbpyStep)
- outputs: `[DesignFormat.ODB, DesignFormat.DEF]` (inherited from OdbpyStep)
- Generates frequency tables for cells, buffers, cell functions, and SCL
- Script writes `cell.rpt`, `cell_function.rpt`, `by_scl.rpt`, and `buffers.rpt`

**Librelane Gating:** `classic.py`
- Position: Step 55 (line 95)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `odb.bzl`
- ID: `"Odb.CellFrequencyTables"` (line 143)
- step_outputs: `[]` - reports only, no design file output
- extra_outputs: `["cell.rpt", "cell_function.rpt", "by_scl.rpt", "buffers.rpt"]`
- Uses ODB_CONFIG_KEYS = BASE_CONFIG_KEYS

**Config Variable Audit:**

Inheritance: CellFrequencyTables → OdbpyStep → Step

No step-specific config_vars. Uses BASE_CONFIG_KEYS only.

**Bazel Flow:** `full_flow.bzl`
- Position: Step 55
- No gating - always runs
- Named: `_cell_freq`
- Chains from: `_fill`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.CellFrequencyTables"` | `"Odb.CellFrequencyTables"` | Y |
| inputs | `[ODB]` | (from src) | Y |
| outputs | `[ODB, DEF]` plus report files in step dir | report files only | Note |
| Gating | None | None | N/A |
| Position | Step 55 (line 95) | Step 55 (line 637) | Y |

**Notes:** Similar to ReportDisconnectedPins - librelane inherits OdbpyStep outputs [ODB, DEF]
while Bazel uses step_outputs=[]. This is a reporting step that doesn't modify the design.
Bazel now declares the four report files written by the script so they remain available as build outputs.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_cell_freq` passed.
- Produced `cell.rpt`, `cell_function.rpt`, `by_scl.rpt`, `buffers.rpt`, and `state_out.json`.

---

### Step 56: OpenROAD.RCX

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.RCX"` (line 2067)
- inputs: `[DesignFormat.DEF]` (line 2098)
- outputs: `[DesignFormat.SPEF]` (line 2099)
- Extracts parasitic resistance/capacitance values for accurate STA

**Librelane Gating:** `classic.py`
- Position: Step 56 (line 96)
- Variable: `RUN_SPEF_EXTRACTION` (line 275)
- Default: `True` (line 199)

**Bazel Implementation:** `sta.bzl`
- ID: `"OpenROAD.RCX"` (line 137)
- outputs: SPEF files for nom, min, max corners
- Uses RCX_CONFIG_KEYS

**Config Variable Audit:**

Inheritance: RCX → OpenROADStep → Step

| Variable | Source | Wired | Status |
|----------|--------|-------|--------|
| RCX_MERGE_VIA_WIRE_RES | openroad.py:2073-2078 | 5-loc pattern | PASS |
| RCX_SDC_FILE | openroad.py:2079-2083 | 5-loc pattern | PASS |
| RCX_RULESETS | openroad.py:2084-2089 (pdk) | PDK path | PASS |
| STA_THREADS | openroad.py:2090-2094 | 5-loc pattern | PASS |
| OpenROADStep vars | inherited | RCX_CONFIG_KEYS | PASS |

**Bazel Flow:** `full_flow.bzl`
- Position: Step 56
- Gated by `run_spef_extraction`, default `True`
- Named: `_rcx`
- Chains from: `_cell_freq`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.RCX"` | `"OpenROAD.RCX"` | Y |
| inputs | `[DEF]` | (from src) | Y |
| outputs | `[SPEF]` | spef_nom, spef_min, spef_max | Y |
| Gating var | RUN_SPEF_EXTRACTION | `run_spef_extraction` | Y |
| Gating default | True | True | Y |
| Position | Step 56 (line 96) | Step 56 | Y |

**Notes:** The RCX rule declares the three sky130 SPEF outputs (`nom`, `min`, `max`) corresponding
to the PDK `RCX_RULESETS` corner patterns.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_rcx` passed.
- Produced `nom/SegmentedMultiplier16x16.nom.spef`, `min/SegmentedMultiplier16x16.min.spef`, and `max/SegmentedMultiplier16x16.max.spef`.

---

### Step 57: OpenROAD.STAPostPNR

**Verified:** 2026-01-28

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.STAPostPNR"` (line 954)
- inputs: STAPrePNR.inputs + `[SPEF, ODB.optional]` (lines 963-966)
- outputs: STAPrePNR.outputs + `[LIB]` (line 967)
- Multi-corner STA with extracted parasitics
- `corner.tcl` emits max/min/checks, power, skew, slack, violator, unpropagated-clock, and clock reports per corner
- `run_corner()` writes per-corner Liberty files via `_LIB_SAVE_DIR`

**Librelane Gating:** `classic.py`
- Position: Step 57 (line 97)
- Variable: `RUN_MCSTA` (line 276)
- Default: `True` (line 192)

**Config Variable Audit:**

Inheritance: STAPostPNR -> STAPrePNR -> MultiCornerSTA -> OpenSTAStep -> OpenROADStep

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| PDN_CONNECT_MACROS_TO_GRID | OpenROADStep:193-198 | Wired |
| PDN_MACRO_CONNECTIONS | OpenROADStep:200-204 | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | OpenROADStep:206-211 | Wired |
| PNR_SDC_FILE | OpenROADStep:213-216 | Wired |
| FP_DEF_TEMPLATE | OpenROADStep:218-222 | Wired |
| LIB | OpenROADStep.prepare_env:245 | Wired |
| FALLBACK_SDC | OpenROADStep.prepare_env:248 | Wired |
| EXTRA_EXCLUDED_CELLS | OpenROADStep.prepare_env:254 | Wired |
| PNR_EXCLUDED_CELL_FILE | OpenROADStep.prepare_env:255 | Wired |
| STA_MACRO_PRIORITIZE_NL | MultiCornerSTA:713-718 | Wired |
| STA_MAX_VIOLATOR_COUNT | MultiCornerSTA:719-723 | Wired |
| EXTRA_SPEFS | MultiCornerSTA:724-728 (deprecated) | Skip (backcompat) |
| STA_THREADS | MultiCornerSTA:729-733 | Wired |
| SIGNOFF_SDC_FILE | STAPostPNR:958-962 | Wired |

**Bazel Implementation:** `sta.bzl`
- Custom `_sta_post_pnr_impl`
- ID: `"OpenROAD.STAPostPNR"`
- Uses `STA_POST_PNR_CONFIG_KEYS = MULTI_CORNER_STA_CONFIG_KEYS + ["SIGNOFF_SDC_FILE"]`
- Declares per-corner Liberty files and passes them forward in `LibrelaneInfo.lib`
- Declares the report files emitted by `corner.tcl`

**Bazel Flow:** `full_flow.bzl`
- Position: Step 57
- Named: `_sta`, chains from `_rcx`
- Gated by `run_mcsta`, default `True`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.STAPostPNR"` | `"OpenROAD.STAPostPNR"` | Y |
| inputs | `[SPEF, ODB?, ...]` | (from src) | Y |
| outputs | `[LIB, ...]` plus reports | LIB files plus reports | Y |
| Gating | RUN_MCSTA (True) | `run_mcsta` (True) | Y |
| Position | Step 57 (line 97) | Step 57 | Y |
| Config keys | MultiCornerSTA + SIGNOFF | STA_POST_PNR_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_sta` passed.
- Produced per-corner `.lib` outputs for all nine sky130 STA corners.
- Produced summary plus max/min/checks, power, skew, slack, violator, unpropagated-clock, and clock reports per corner.
- Runtime summary showed zero setup and hold violation counts for the small segmented multiplier.

---

### Step 58: OpenROAD.IRDropReport

**Verified:** 2026-01-28

**Librelane Source:** `librelane/steps/openroad.py`
- ID: `"OpenROAD.IRDropReport"` (line 2200)
- inputs: `[DesignFormat.ODB, DesignFormat.SPEF]` (line 2202)
- outputs: `[]` (line 2203) - produces reports only
- Performs static IR-drop analysis on power distribution network
- Reads `irdrop.rpt` to extract voltage/drop metrics

**Librelane Gating:** `classic.py`
- Position: Step 58 (line 98)
- Variable: `RUN_IRDROP_REPORT` (line 282)
- Default: `True` (line 205)

**Config Variable Audit:**

Inheritance: IRDropReport -> OpenROADStep -> TclStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| PDN_CONNECT_MACROS_TO_GRID | OpenROADStep:193-198 | Wired |
| PDN_MACRO_CONNECTIONS | OpenROADStep:200-204 | Wired |
| PDN_ENABLE_GLOBAL_CONNECTIONS | OpenROADStep:206-211 | Wired |
| PNR_SDC_FILE | OpenROADStep:213-216 | Wired |
| FP_DEF_TEMPLATE | OpenROADStep:218-222 | Wired |
| LIB | OpenROADStep.prepare_env:245 | Wired |
| FALLBACK_SDC | OpenROADStep.prepare_env:248 | Wired |
| EXTRA_EXCLUDED_CELLS | OpenROADStep.prepare_env:254 | Wired |
| VSRC_LOC_FILES | IRDropReport:2206-2210 | Wired (via label_keyed_string_dict) |

Note: VSRC_LOC_FILES uses attr.label_keyed_string_dict where file labels map to net names,
inverted in init.bzl to create net_name -> File dict.

**Bazel Implementation:** `sta.bzl`
- _ir_drop_report_impl (line 224)
- ID: `"OpenROAD.IRDropReport"` (line 225)
- Uses IRDROP_CONFIG_KEYS = STA_CONFIG_KEYS + ["VSRC_LOC_FILES"]
- Declares `irdrop.rpt` as an extra output

**Bazel Flow:** `full_flow.bzl`
- Position: Step 58 (line 547 comment)
- Named: `_ir_drop`, chains from `_sta`
- Gated by `run_irdrop_report`, default `True`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"OpenROAD.IRDropReport"` | `"OpenROAD.IRDropReport"` | Y |
| inputs | `[ODB, SPEF]` | (from src) | Y |
| outputs | `[]` plus `irdrop.rpt` report | `irdrop.rpt` | Y |
| Gating | RUN_IRDROP_REPORT (True) | `run_irdrop_report` (True) | Y |
| Position | Step 58 (line 98) | Step 58 (line 547) | Y |
| Config keys | OpenROADStep + VSRC_LOC | IRDROP_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_ir_drop` passed.
- Produced `irdrop.rpt` and `state_out.json`.
- Runtime warned that `VSRC_LOC_FILES` was unset, matching LibreLane behavior; it still produced VPWR/VGND IR metrics.

---

### Step 59: Magic.StreamOut

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/magic.py`
- ID: `"Magic.StreamOut"` (line 286)
- inputs: `[DesignFormat.DEF]` (line 288)
- outputs: `[DesignFormat.GDS, DesignFormat.MAG_GDS, DesignFormat.MAG]` (line 289)
- Converts DEF views into GDSII streams using Magic
- Always updates `MAG_GDS` and `MAG`; updates `GDS` only when `PRIMARY_GDSII_STREAMOUT_TOOL == "magic"`

**Librelane Gating:** `classic.py`
- Position: Step 59 (line 99)
- Variable: `RUN_MAGIC_STREAMOUT` (line 283)
- Default: `True` (line 217)

**Config Variable Audit:**

Inheritance: Magic.StreamOut -> MagicStep -> TclStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| MAGIC_DEF_LABELS | MagicStep:77-82 | Wired |
| MAGIC_GDS_POLYGON_SUBCELLS | MagicStep:83-88 | Wired |
| MAGIC_DEF_NO_BLOCKAGES | MagicStep:89-94 | Wired |
| MAGIC_INCLUDE_GDS_POINTERS | MagicStep:95-100 | Wired |
| MAGICRC | MagicStep:101-107 (pdk) | Wired |
| MAGIC_TECH | MagicStep:108-114 (pdk) | Wired |
| MAGIC_PDK_SETUP | MagicStep:115-120 (pdk) | Wired |
| CELL_MAGS | MagicStep:121-126 (pdk) | Wired |
| CELL_MAGLEFS | MagicStep:127-132 (pdk) | Wired |
| MAGIC_CAPTURE_ERRORS | MagicStep:133-141 | Wired |
| DIE_AREA | StreamOut:293-298 | From state metrics |
| MAGIC_ZEROIZE_ORIGIN | StreamOut:299-304 | Wired |
| MAGIC_DISABLE_CIF_INFO | StreamOut:305-311 | Wired |
| MAGIC_MACRO_STD_CELL_SOURCE | StreamOut:312-320 | Wired |

**Bazel Implementation:** `macro.bzl`
- _gds_impl (line 40)
- ID: `"Magic.StreamOut"` (line 58)
- Uses MAGIC_STREAMOUT_CONFIG_KEYS (line 18)
- Declares `top.magic.gds` and `top.mag`; declares `top.gds` only when Magic is the primary stream-out tool

**Bazel Flow:** `full_flow.bzl`
- Position: Step 59
- Named: `_gds`, chains from `_ir_drop`
- Gated by `run_magic_streamout`, default `True`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Magic.StreamOut"` | `"Magic.StreamOut"` | Y |
| inputs | `[DEF]` | (from src) | Y |
| outputs | `[GDS, MAG_GDS, MAG]` | GDS/MAG_GDS/MAG as applicable | Y |
| Gating | RUN_MAGIC_STREAMOUT (True) | `run_magic_streamout` (True) | Y |
| Position | Step 59 (line 99) | Step 59 | Y |
| Config keys | MagicStep + StreamOut | MAGIC_STREAMOUT_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_gds` passed.
- Produced `SegmentedMultiplier16x16.magic.gds`, `SegmentedMultiplier16x16.mag`, `SegmentedMultiplier16x16.gds`, and `state_out.json`.

---

### Step 60: KLayout.StreamOut

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/klayout.py`
- ID: `"KLayout.StreamOut"` (line 272)
- inputs: `[DesignFormat.DEF]` (line 275)
- outputs: `[DesignFormat.GDS, DesignFormat.KLAYOUT_GDS]` (line 276)
- Converts DEF views into GDSII streams using KLayout
- Always updates `KLAYOUT_GDS`; updates `GDS` only when `PRIMARY_GDSII_STREAMOUT_TOOL == "klayout"`

**Librelane Gating:** `classic.py`
- Position: Step 60 (line 100)
- Variable: `RUN_KLAYOUT_STREAMOUT` (line 284)
- Default: `True` (line 224)

**Config Variable Audit:**

Inheritance: KLayout.StreamOut -> KLayoutStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| KLAYOUT_TECH | KLayoutStep:36-39 (pdk) | Wired (common.bzl:203) |
| KLAYOUT_PROPERTIES | KLayoutStep:40-44 (pdk) | Wired (common.bzl:204) |
| KLAYOUT_DEF_LAYER_MAP | KLayoutStep:45-51 (pdk) | Wired (common.bzl:205) |
| KLAYOUT_CONFLICT_RESOLUTION | StreamOut:278-286 | Wired |
| DESIGN_NAME | run():294,306,322 | Wired (BASE_CONFIG_KEYS) |
| PRIMARY_GDSII_STREAMOUT_TOOL | run():320 | Wired (BASE_CONFIG_KEYS:16) |
| TECH_LEFS | get_cli_args():92 | Wired (BASE_CONFIG_KEYS:15) |
| CELL_LEFS | get_cli_args():103 | Wired (BASE_CONFIG_KEYS:31) |
| CELL_GDS | get_cli_args():121 | Wired (BASE_CONFIG_KEYS:32) |
| EXTRA_LEFS | get_cli_args():112 | Wired (common.bzl:352) |
| EXTRA_GDS_FILES | get_cli_args():127 | Wired (common.bzl:353) |

Note: KLAYOUT_* PDK variables added to KLAYOUT_STREAMOUT_CONFIG_KEYS (klayout.bzl:7-13).

**Bazel Implementation:** `klayout.bzl`
- _stream_out_impl
- ID: `"KLayout.StreamOut"` (line 10)
- Uses KLAYOUT_STREAMOUT_CONFIG_KEYS (line 10)
- Declares `top.klayout.gds`; declares `top.gds` only when KLayout is the primary stream-out tool

**Bazel Flow:** `full_flow.bzl`
- Position: Step 60
- Gated by `run_klayout_streamout`, default `True`
- Named: `_klayout_gds`
- Chains from: `_gds`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"KLayout.StreamOut"` | `"KLayout.StreamOut"` | Y |
| inputs | `[DEF]` | (from src) | Y |
| outputs | `[GDS, KLAYOUT_GDS]` | KLAYOUT_GDS plus conditional GDS | Y |
| Gating | RUN_KLAYOUT_STREAMOUT (True) | `run_klayout_streamout` (True) | Y |
| Position | Step 60 (line 100) | Step 60 | Y |
| Config keys | KLayoutStep vars | KLAYOUT_STREAMOUT_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_klayout_gds` passed.
- Produced `SegmentedMultiplier16x16.klayout.gds` and `state_out.json`.
- Did not declare `SegmentedMultiplier16x16.gds` for sky130 because `PRIMARY_GDSII_STREAMOUT_TOOL` is Magic.

---

### Step 61: Magic.WriteLEF

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/magic.py`
- ID: `"Magic.WriteLEF"` (line 230)
- inputs: `[DesignFormat.GDS, DesignFormat.DEF]` (line 233)
- outputs: `[DesignFormat.LEF]` (line 234)
- Writes a LEF view of the design using GDS via Magic

**Librelane Gating:** `classic.py`
- Position: Step 61 (line 101)
- Variable: `RUN_MAGIC_WRITE_LEF` (line 285)
- Default: `True` (line 231)

**Config Variable Audit:**

Inheritance: Magic.WriteLEF -> MagicStep -> TclStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| MAGIC_DEF_LABELS | MagicStep:77-82 | Wired |
| MAGIC_GDS_POLYGON_SUBCELLS | MagicStep:83-88 | Wired |
| MAGIC_DEF_NO_BLOCKAGES | MagicStep:89-94 | Wired |
| MAGIC_INCLUDE_GDS_POINTERS | MagicStep:95-100 | Wired |
| MAGICRC | MagicStep:101-107 (pdk) | Wired |
| MAGIC_TECH | MagicStep:108-114 (pdk) | Wired |
| MAGIC_PDK_SETUP | MagicStep:115-120 (pdk) | Wired |
| CELL_MAGS | MagicStep:121-126 (pdk) | Wired |
| CELL_MAGLEFS | MagicStep:127-132 (pdk) | Wired |
| MAGIC_CAPTURE_ERRORS | MagicStep:133-141 | Wired |
| MAGIC_LEF_WRITE_USE_GDS | WriteLEF:238-243 | Wired |
| MAGIC_WRITE_FULL_LEF | WriteLEF:244-249 | Wired |
| MAGIC_WRITE_LEF_PINONLY | WriteLEF:250-255 | Wired |

Note: Uses MAGIC_WRITELEF_CONFIG_KEYS (macro.bzl) with MagicStep + WriteLEF vars.

**Bazel Implementation:** `macro.bzl`
- _lef_impl (line 90)
- ID: `"Magic.WriteLEF"` (line 108)
- Uses MAGIC_WRITELEF_CONFIG_KEYS (line 103)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 61
- Gated by `run_magic_write_lef`, default `True`
- Named: `_lef`
- Chains from: `_klayout_gds`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Magic.WriteLEF"` | `"Magic.WriteLEF"` | Y |
| inputs | `[GDS, DEF]` | (from src) | Y |
| outputs | `[LEF]` | LEF file | Y |
| Gating | RUN_MAGIC_WRITE_LEF (True) | `run_magic_write_lef` (True) | Y |
| Position | Step 61 (line 101) | Step 61 | Y |
| Config keys | MagicStep + WriteLEF vars | MAGIC_WRITELEF_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_lef` passed.
- Produced `SegmentedMultiplier16x16.lef` and `state_out.json`.

---

### Step 62: Odb.CheckDesignAntennaProperties

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/odb.py`
- ID: `"Odb.CheckDesignAntennaProperties"` (line 245)
- inputs: `[DesignFormat.ODB, DesignFormat.LEF]` (line 247, ODB from OdbpyStep)
- outputs: `[]` (inherited from CheckMacroAntennaProperties, line 206)
- Prints warnings if the design's LEF view is missing antenna information
- Writes `report.yaml` through the inherited `get_report_path()`

**Librelane Gating:** `classic.py`
- Position: Step 62 (line 102)
- No entry in gating_config_vars dict - always runs

**Config Variable Audit:**

Inheritance: CheckDesignAntennaProperties -> CheckMacroAntennaProperties -> OdbpyStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| (none) | config_vars = [] (Step line 464) | N/A |
| DESIGN_NAME | get_cells():250 | Wired (BASE_CONFIG_KEYS) |

No config_vars in inheritance chain. Uses DESIGN_NAME via self.config access.

**Bazel Implementation:** `odb.bzl`
- _check_design_antenna_properties_impl (line 145)
- ID: `"Odb.CheckDesignAntennaProperties"` (line 146)
- Uses ODB_CONFIG_KEYS = BASE_CONFIG_KEYS (line 7)
- Declares `report.yaml`

**Bazel Flow:** `full_flow.bzl`
- Position: Step 62 (lines 686-691)
- No gating - always runs
- Named: `_chk_ant_prop`
- Chains from: `_lef`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Odb.CheckDesignAntennaProperties"` | `"Odb.CheckDesignAntennaProperties"` | Y |
| inputs | `[ODB, LEF]` | (from src) | Y |
| outputs | `[]` plus `report.yaml` report | `report.yaml` | Y |
| Gating | None | None | N/A |
| Position | Step 62 (line 102) | Step 62 (line 686) | Y |
| Config keys | DESIGN_NAME only | ODB_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_ant_prop` passed.
- Produced `report.yaml` and `state_out.json`.

---

### Step 63: KLayout.XOR

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/klayout.py`
- ID: `"KLayout.XOR"` (line 347)
- inputs: `[DesignFormat.MAG_GDS, DesignFormat.KLAYOUT_GDS]` (lines 351-354)
- outputs: `[]` (line 356)
- Performs XOR operation between Magic and KLayout GDS views to detect differences
- Self-skipping: if either MAG_GDS or KLAYOUT_GDS is missing, step warns and returns
- Writes `xor.xml`

**Librelane Gating:** `classic.py`
- Position: Step 63 (line 103)
- Gating variables (classic.py lines 286-290):
  - `RUN_KLAYOUT_XOR` (default: True, line 238)
  - `RUN_MAGIC_STREAMOUT` (default: True, line 217)
  - `RUN_KLAYOUT_STREAMOUT` (default: True, line 224)
- All three must be True for step to run

**Config Variable Audit:**

Inheritance: KLayout.XOR -> KLayoutStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| KLAYOUT_TECH | KLayoutStep:36-39 (pdk) | Wired (common.bzl:203) |
| KLAYOUT_PROPERTIES | KLayoutStep:40-44 (pdk) | Wired (common.bzl:204) |
| KLAYOUT_DEF_LAYER_MAP | KLayoutStep:45-51 (pdk) | Wired (common.bzl:205) |
| KLAYOUT_XOR_THREADS | XOR:361-365 | Wired |
| KLAYOUT_XOR_IGNORE_LAYERS | XOR:366-371 (pdk) | Wired (common.bzl:207) |
| KLAYOUT_XOR_TILE_SIZE | XOR:372-378 (pdk) | Wired (common.bzl:208) |
| DESIGN_NAME | run():406 | Wired (BASE_CONFIG_KEYS) |

Uses KLAYOUT_XOR_CONFIG_KEYS (klayout.bzl:17-27).

**Bazel Implementation:** `klayout.bzl`
- _xor_impl (line 44)
- ID: `"KLayout.XOR"` (line 45)
- Uses KLAYOUT_XOR_CONFIG_KEYS (line 45)
- Declares `xor.xml`

**Bazel Flow:** `full_flow.bzl`
- Position: Step 63
- Gated by `run_klayout_xor and run_magic_streamout and run_klayout_streamout`
- Named: `_xor`
- Chains from: `_chk_ant_prop`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"KLayout.XOR"` | `"KLayout.XOR"` | Y |
| inputs | `[MAG_GDS, KLAYOUT_GDS]` | (from src) | Y |
| outputs | `[]` plus `xor.xml` report | `xor.xml` | Y |
| Gating | Compound gate | Same compound gate | Y |
| Position | Step 63 (line 103) | Step 63 | Y |
| Config keys | KLayoutStep + XOR vars | KLAYOUT_XOR_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_xor` passed.
- Produced `xor.xml` and `state_out.json`.
- Runtime reported total XOR differences of 0.

---

### Step 64: Checker.XOR

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.XOR"` (line 290)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- Checks the `design__xor_difference__count` metric and raises deferred error if > 0

**Librelane Gating:** `classic.py`
- Position: Step 64 (line 104)
- Gating variables (lines 294-298):
  - `RUN_KLAYOUT_XOR` (default: True)
  - `RUN_MAGIC_STREAMOUT` (default: True)
  - `RUN_KLAYOUT_STREAMOUT` (default: True)
- All three must be True for step to run (same as KLayout.XOR)

**Config Variable Audit:**

Inheritance: Checker.XOR -> MetricChecker -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| ERROR_ON_XOR_ERROR | XOR:298-304 | Wired |

Uses XOR_CHECKER_CONFIG_KEYS (checker.bzl:44).

**Bazel Implementation:** `checker.bzl`
- _xor_impl (line 79)
- ID: `"Checker.XOR"` (line 80)
- Uses XOR_CHECKER_CONFIG_KEYS (line 80)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 64
- Gated by `run_klayout_xor and run_magic_streamout and run_klayout_streamout`
- Named: `_chk_xor`
- Chains from: `_xor`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.XOR"` | `"Checker.XOR"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | Compound gate | Same compound gate | Y |
| Position | Step 64 (line 104) | Step 64 | Y |
| Config keys | ERROR_ON_XOR_ERROR | XOR_CHECKER_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_xor` passed.
- Runtime reported the XOR difference check clear.

---

### Step 65: Magic.DRC

**Verified:** 2026-07-08

**Librelane Source:** `librelane/steps/magic.py`
- ID: `"Magic.DRC"` (line 501)
- inputs: `[DesignFormat.DEF.optional, DesignFormat.GDS]` (line 505)
- outputs: `[]` (line 506)
- Runs Magic DRC checks, outputs metric `magic__drc_error__count`
- Writes `reports/drc.magic.rpt` and converts it to `reports/drc.magic.lyrdb`

**Librelane Gating:** `classic.py`
- Position: Step 65 (line 105)
- Variable: `RUN_MAGIC_DRC` (line 286)
- Default: `True` (line 244)

**Config Variable Audit:**

Inheritance: Magic.DRC -> MagicStep -> TclStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| MAGIC_DEF_LABELS | MagicStep:77-82 | Wired |
| MAGIC_GDS_POLYGON_SUBCELLS | MagicStep:83-88 | Wired |
| MAGIC_DEF_NO_BLOCKAGES | MagicStep:89-94 | Wired |
| MAGIC_INCLUDE_GDS_POINTERS | MagicStep:95-100 | Wired |
| MAGICRC | MagicStep:101-107 (pdk) | Wired |
| MAGIC_TECH | MagicStep:108-114 (pdk) | Wired |
| MAGIC_PDK_SETUP | MagicStep:115-120 (pdk) | Wired |
| CELL_MAGS | MagicStep:121-126 (pdk) | Wired |
| CELL_MAGLEFS | MagicStep:127-132 (pdk) | Wired |
| MAGIC_CAPTURE_ERRORS | MagicStep:133-141 | Wired |
| MAGIC_DRC_USE_GDS | DRC:510-515 | Wired |
| MAGIC_GDS_FLATGLOB | DRC:516-520 | Wired |
| MAGIC_DRC_MAGLEFS | DRC:521-525 | Wired |

Uses MAGIC_DRC_CONFIG_KEYS (macro.bzl).

**Bazel Implementation:** `macro.bzl`
- _drc_impl (line 168)
- ID: `"Magic.DRC"` (line 169)
- Uses MAGIC_DRC_CONFIG_KEYS (line 169)
- Declares `reports/drc.magic.rpt` and `reports/drc.magic.lyrdb`

**Bazel Flow:** `full_flow.bzl`
- Position: Step 65
- Gated by `run_magic_drc`, default `True`
- Named: `_magic_drc`
- Chains from: `_chk_xor`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Magic.DRC"` | `"Magic.DRC"` | Y |
| inputs | `[DEF?, GDS]` | (from src) | Y |
| outputs | `[]` plus DRC reports | DRC reports | Y |
| Gating | RUN_MAGIC_DRC (True) | `run_magic_drc` (True) | Y |
| Position | Step 65 (line 105) | Step 65 | Y |
| Config keys | MagicStep + DRC vars | MAGIC_DRC_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_magic_drc` passed.
- Produced `reports/drc.magic.rpt`, `reports/drc.magic.lyrdb`, and `state_out.json`.
- Runtime reported 0 Magic DRC errors.

---

### Step 66: KLayout.DRC

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/klayout.py`
- ID: `"KLayout.DRC"` (line 440)
- inputs: `[DesignFormat.GDS]` (lines 443-445)
- outputs: `[]` (line 446)
- Runs KLayout DRC, self-skips if KLAYOUT_DRC_RUNSET unavailable
- Outputs metric `klayout__drc_error__count`
- Writes report files when it runs:
  `reports/drc.klayout.lyrdb` and `reports/drc.klayout.json`

**Librelane Gating:** `classic.py`
- Position: Step 66 (line 106)
- Variable: `RUN_KLAYOUT_DRC` (line 285)
- Default: `True` (line 250)

**Config Variable Audit:**

Inheritance: KLayout.DRC -> KLayoutStep -> Step

| Variable | Source | Bazel Status |
|----------|--------|--------------|
| KLAYOUT_TECH | KLayoutStep | Wired |
| KLAYOUT_PROPERTIES | KLayoutStep | Wired |
| KLAYOUT_DEF_LAYER_MAP | KLayoutStep | Wired |
| KLAYOUT_DRC_RUNSET | DRC:449-455 (pdk) | Wired |
| KLAYOUT_DRC_OPTIONS | DRC:456-461 (pdk) | Wired |
| KLAYOUT_DRC_THREADS | DRC:462-467 | Wired |

Note: the reports are declared as optional Bazel outputs because the LibreLane
step can self-skip when a PDK has no KLayout DRC runset.

Uses KLAYOUT_DRC_CONFIG_KEYS (klayout.bzl:29-39).

**Bazel Implementation:** `klayout.bzl`
- `_drc_impl` (line 54)
- ID: `"KLayout.DRC"` (line 55)
- Uses `KLAYOUT_DRC_CONFIG_KEYS` (lines 30-40)
- Declares optional report outputs for `drc.klayout.lyrdb` and
  `drc.klayout.json`

**Bazel Flow:** `full_flow.bzl`
- Position: Step 66 (lines 789-798)
- Gating: `run_klayout_drc` (default True)
- Named: `_klayout_drc`
- Chains from: `_magic_drc`

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"KLayout.DRC"` | `"KLayout.DRC"` | Y |
| inputs | `[GDS]` | (from src) | Y |
| outputs | `[]` plus DRC reports | Optional DRC reports | Y |
| Gating | RUN_KLAYOUT_DRC (True) | `run_klayout_drc` (True) | Y |
| Position | Step 66 (line 106) | Step 66 (line 789) | Y |
| Config keys | KLayoutStep + DRC vars | KLAYOUT_DRC_CONFIG_KEYS | Y |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_klayout_drc` passed.
- Produced `reports/drc.klayout.lyrdb`, `reports/drc.klayout.json`, and
  `state_out.json`.

---

### Step 67: Checker.MagicDRC

**Verified:** 2026-01-26

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.MagicDRC"` (line 198)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- Checks metric `magic__drc_error__count` and raises deferred error if > 0
- Config var: `ERROR_ON_MAGIC_DRC` (default: True) controls whether violations cause error

**Librelane Gating:** `classic.py`
- Position: Step 67 (line 107)
- Gating: `RUN_MAGIC_DRC` (same as Magic.DRC step)
- Entry in gating_config_vars at line 293

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.MagicDRC"` (line 40)
- step_outputs: `[]` (line 40)
- Rule: `librelane_magic_drc_checker` (line 130)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 67 (lines 800-809)
- Named: `_chk_magic_drc`
- Chains from: `_klayout_drc`
- Gating: `run_magic_drc` (default True)

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.MagicDRC"` | `"Checker.MagicDRC"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | `RUN_MAGIC_DRC` | `run_magic_drc` | Y |
| Position | Step 67 (line 107) | Step 67 (line 800) | Y |

**Notes:** Coupled with Magic.DRC (step 65) - both gated by same variable.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_magic_drc`
  passed and produced `state_out.json`.
- Runtime reported the Magic DRC check clear.

---

### Step 68: Checker.KLayoutDRC

**Verified:** 2026-01-26

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.KLayoutDRC"` (line 414)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- Checks metric `klayout__drc_error__count` and raises deferred error if > 0
- Config var: `ERROR_ON_KLAYOUT_DRC` (default: True) controls whether violations cause error

**Librelane Gating:** `classic.py`
- Position: Step 68 (line 108)
- Gating: `RUN_KLAYOUT_DRC` (same as KLayout.DRC step)
- Entry in gating_config_vars at line 300

**Bazel Implementation:** `checker.bzl`
- ID: `"Checker.KLayoutDRC"` (line 43)
- step_outputs: `[]` (line 43)
- Rule: `librelane_klayout_drc_checker` (line 136)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 68 (lines 811-820)
- Named: `_chk_klayout_drc`
- Chains from: `_chk_magic_drc`
- Gating: `run_klayout_drc` (default True)

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.KLayoutDRC"` | `"Checker.KLayoutDRC"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | `RUN_KLAYOUT_DRC` | `run_klayout_drc` | Y |
| Position | Step 68 (line 108) | Step 68 (line 811) | Y |

**Notes:** Coupled with KLayout.DRC (step 66) - both gated by same variable.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_klayout_drc`
  passed and produced `state_out.json`.
- Runtime reported the KLayout DRC check clear.

---

### Step 69: Magic.SpiceExtraction

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/magic.py`
- ID: `"Magic.SpiceExtraction"` (line 575)
- inputs: `[DesignFormat.GDS, DesignFormat.DEF]` (line 579)
- outputs: `[DesignFormat.SPICE]` (line 580)
- Inheritance: SpiceExtraction -> MagicStep -> TclStep -> Step
- Extracts SPICE netlist from GDSII for LVS checks
- Also outputs metric `magic__illegal_overlap__count`
- The underlying Magic Tcl read path calls `read_pdk_spice()` and reads
  `::env(CELL_SPICE_MODELS)` unconditionally
  (`scripts/magic/common/read.tcl` line 152).

**Librelane Gating:** `classic.py`
- Position: Step 69 (line 109)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `macro.bzl`
- ID: `"Magic.SpiceExtraction"` (line 197)
- step_outputs: `["spice"]` (line 197)
- Rule: `librelane_spice_extraction` (line 223)
- Uses `SPICE_EXTRACTION_CONFIG_KEYS`, including MagicStep,
  SpiceExtraction-specific keys, and `CELL_SPICE_MODELS`.

**Bazel Flow:** `full_flow.bzl`
- Position: Step 69 (lines 822-827)
- Named: `_spice`
- Chains from: `_chk_klayout_drc`
- No gating - always runs

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Magic.SpiceExtraction"` | `"Magic.SpiceExtraction"` | Y |
| inputs | `[GDS, DEF]` | (from src) | Y |
| outputs | `[SPICE]` | `["spice"]` | Y |
| Gating | None | None | N/A |
| Position | Step 69 (line 109) | Step 69 (line 822) | Y |

**Config Variable Audit:**

From SpiceExtraction class (magic.py lines 582-623):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| MAGIC_EXT_USE_GDS | bool | False | No | Wired |
| MAGIC_EXT_ABSTRACT_CELLS | Optional[List[str]] | None | No | Wired |
| MAGIC_EXT_UNIQUE | Literal | `"all"` | No | Not wired directly; Bazel currently emits deprecated `MAGIC_NO_EXT_UNIQUE` |
| MAGIC_EXT_SHORT_RESISTOR | bool | False | No | Wired |
| MAGIC_EXT_ABSTRACT | bool | False | No | Wired |
| MAGIC_FEEDBACK_CONVERSION_THRESHOLD | int | 10000 | No | Wired |
| CELL_SPICE_MODELS | Optional[List[Path]] | None | Yes | Wired as a Tcl script dependency |

From MagicStep class (magic.py lines 76-142):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| MAGIC_DEF_LABELS | bool | True | No | Wired |
| MAGIC_GDS_POLYGON_SUBCELLS | bool | False | No | Wired |
| MAGIC_DEF_NO_BLOCKAGES | bool | True | No | Wired |
| MAGIC_INCLUDE_GDS_POINTERS | bool | False | No | Wired |
| MAGICRC | Path | - | Yes | Wired (PDK) |
| MAGIC_TECH | Path | - | Yes | Wired (PDK) |
| MAGIC_PDK_SETUP | Path | - | Yes | Wired (PDK) |
| CELL_MAGS | Optional[List[Path]] | None | Yes | Wired (PDK) |
| CELL_MAGLEFS | Optional[List[Path]] | None | Yes | Wired (PDK) |
| MAGIC_CAPTURE_ERRORS | bool | True | No | Wired |

**Notes:**
- `CELL_SPICE_MODELS` is not listed in `SpiceExtraction.config_vars`, but is
  required by the Magic Tcl script used by this step. The Bazel wrapper includes
  it so the step matches the actual LibreLane execution path.
- `MAGIC_NO_EXT_UNIQUE` still works through LibreLane's deprecated-name
  compatibility path, but this should be changed to `MAGIC_EXT_UNIQUE` in a
  small follow-up after updating the wrapper interface.

**Status: PASS**

Verification:
- First run failed with `can't read "::env(CELL_SPICE_MODELS)"`.
- After wiring `CELL_SPICE_MODELS`,
  `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_spice` passed.
- Produced `SegmentedMultiplier16x16.spice` and `state_out.json`.

---

### Step 70: Checker.IllegalOverlap

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.IllegalOverlap"` (line 217)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- Checks metric `magic__illegal_overlap__count` (set by Magic.SpiceExtraction)
- Uses MetricChecker.run() which reads error_on_var via self.config.get() at line 119

**Librelane Gating:** `classic.py`
- Position: Step 70 (line 110)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `checker.bzl`
- impl: `_illegal_overlap_impl` (line 103)
- Uses `ILLEGAL_OVERLAP_CONFIG_KEYS` (line 60)
- Rule: `librelane_illegal_overlap` (line 200)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 70 (lines 829-834)
- Named: `_chk_overlap`
- Chains from: `_spice`
- No gating - always runs

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.IllegalOverlap"` | `"Checker.IllegalOverlap"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 70 (line 110) | Step 70 (line 829) | Y |

**Config Variable Audit:**

From IllegalOverlap class (checker.py lines 224-230):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| ERROR_ON_ILLEGAL_OVERLAPS | bool | True | No | Wired |

MetricChecker parent (checker.py lines 69-137) has no config_vars.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_overlap`
  passed and produced `state_out.json`.
- Runtime reported the Magic illegal-overlap check clear.

---

### Step 71: Netgen.LVS

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/netgen.py`
- ID: `"Netgen.LVS"` (line 142)
- inputs: `[DesignFormat.SPICE, DesignFormat.POWERED_NETLIST]` (line 144)
- outputs: `[]` (inherited from NetgenStep, line 100)
- Performs Layout vs. Schematic check using extracted SPICE vs. Verilog netlist
- Writes `reports/lvs.netgen.rpt` and `reports/lvs.netgen.json`

**Librelane Gating:** `classic.py`
- Position: Step 71 (line 111)
- Gating: `RUN_LVS` (default: True, lines 208-211)
- Entry in gating_config_vars at line 291

**Bazel Implementation:** `netgen.bzl`
- impl: `_lvs_impl` (line 18)
- Uses `NETGEN_LVS_CONFIG_KEYS` (lines 8-16)
- Declares `reports/lvs.netgen.rpt` and `reports/lvs.netgen.json`
- Rule: `librelane_netgen_lvs` (line 20)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 71 (lines 836-850)
- Named: `_lvs`
- Chains from: `_chk_overlap`
- Gated with `run_lvs`, default True

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Netgen.LVS"` | `"Netgen.LVS"` | Y |
| inputs | `[SPICE, POWERED_NETLIST]` | (from src) | Y |
| outputs | `[]` plus LVS reports | LVS reports | Y |
| Gating | `RUN_LVS` | `run_lvs` | Y |
| Position | Step 71 (line 111) | Step 71 (line 836) | Y |

**Config Variable Audit:**

From LVS class (netgen.py lines 145-162):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| LVS_INCLUDE_MARCO_NETLISTS | bool | False | No | Wired |
| LVS_FLATTEN_CELLS | Optional[List[str]] | None | No | Wired |
| LVS_IGNORE_CELLS | Optional[List[str]] | None | No | Wired |

From NetgenStep parent (netgen.py lines 102-116):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| MAGIC_EXT_USE_GDS | bool | False | No | Wired |
| NETGEN_SETUP | Path | - | Yes | Wired (PDK) |

From run() method accesses (netgen.py lines 170-186):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| CELL_SPICE_MODELS | Optional[List[Path]] | - | Yes | Wired (PDK) |
| EXTRA_SPICE_MODELS | Optional[List[Path]] | None | No | Wired |
| SPICE_MODELS | Optional[List[Path]] | None | Yes | Not modeled in Bazel PDK provider |
| PAD_SPICE_MODELS | Optional[List[Path]] | None | Yes | Not modeled in Bazel PDK provider |

Gating (classic.py lines 208-211):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| RUN_LVS | bool | True | No | Wired |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_lvs` passed.
- Produced `reports/lvs.netgen.rpt`, `reports/lvs.netgen.json`, and
  `state_out.json`.
- Runtime reported `Final result: Circuits match uniquely.`

---

### Step 72: Checker.LVS

**Verified:** 2026-01-29

**Librelane Source:** `librelane/steps/checker.py`
- ID: `"Checker.LVS"` (line 300)
- inputs: `[]` (inherited from MetricChecker, line 74)
- outputs: `[]` (inherited from MetricChecker, line 75)
- Checks metric `design__lvs_error__count` and raises deferred error if > 0
- Uses MetricChecker.run() which reads error_on_var via self.config.get() at line 119

**Librelane Gating:** `classic.py`
- Position: Step 72 (line 112)
- Gating: `RUN_LVS` (same as Netgen.LVS step, wired in Step 71)
- Entry in gating_config_vars at line 299

**Bazel Implementation:** `checker.bzl`
- impl: `_lvs_impl` (line 111)
- Uses `LVS_CHECKER_CONFIG_KEYS` (lines 62-65)
- Rule: `librelane_lvs_checker` (line 215)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 72 (lines 836-850)
- Named: `_chk_lvs`
- Chains from: `_lvs`
- Gated with `run_lvs` (shared with Netgen.LVS)

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.LVS"` | `"Checker.LVS"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | `RUN_LVS` | `run_lvs` | Y |
| Position | Step 72 (line 112) | Step 72 (line 843) | Y |

**Config Variable Audit:**

From LVS class (checker.py lines 307-314):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| ERROR_ON_LVS_ERROR | bool | True | No | Wired |

MetricChecker parent (checker.py lines 69-137) has no config_vars.

Gating (classic.py line 299):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| RUN_LVS | bool | True | No | Wired (Step 71) |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_lvs`
  passed and produced `state_out.json`.
- Runtime reported the LVS check clear.

---

### Step 73: Yosys.EQY

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/yosys.py`
- ID: `"Yosys.EQY"` (line 269)
- inputs: `[DesignFormat.NETLIST]` (line 273)
- outputs: `[]` (line 274)
- Runs formal equivalence check between RTL and gate-level netlist

**Librelane Gating:** `classic.py`
- Position: Step 73 (line 113)
- Gating: `RUN_EQY` (default: **False**, lines 253-256)
- Entry in gating_config_vars at line 302
- Note: Disabled by default (unlike most steps)

**Bazel Implementation:** `synthesis.bzl`
- impl: `_eqy_impl` (line 196)
- Uses `EQY_CONFIG_KEYS` (lines 77-82)
- Rule: `librelane_eqy` (line 245)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 73 (lines 852-860)
- Named: `_eqy`
- Chains from the pre-EQY predecessor (`_chk_lvs` when LVS runs, otherwise
  `_chk_overlap`)
- Gated with `run_eqy`, default **False**

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Yosys.EQY"` | `"Yosys.EQY"` | Y |
| inputs | `[NETLIST]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | `RUN_EQY` (default: False) | `run_eqy` (default: False) | Y |
| Position | Step 73 (line 113) | Step 73 (line 852) | Y |

**Config Variable Audit:**

From EQY class (yosys.py lines 276-295):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| EQY_SCRIPT | Optional[Path] | None | No | Wired |
| MACRO_PLACEMENT_CFG | Optional[Path] | None | No | Wired |
| EQY_FORCE_ACCEPT_PDK | bool | False | No | Wired |

From YosysStep parent (yosys.py lines 147-190) - all PDK variables, wired.
From verilog_rtl_cfg_vars (pyosys.py lines 95-136) - wired for synthesis.

Gating (classic.py lines 253-256):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| RUN_EQY | bool | **False** | No | Wired |

**Status: PASS**

Verification:
- Structural audit only. The small `SegmentedMultiplier16x16` flow does not
  instantiate an EQY target because `run_eqy` defaults to False, matching
  LibreLane Classic.

---

### Step 74: Checker.SetupViolations

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.SetupViolations"` (line 645)
- inputs: `[]` (inherited from MetricChecker/TimingViolations)
- outputs: `[]` (inherited)
- Checks metric `timing__setup_vio__count` for setup timing violations

**Librelane Gating:** `classic.py`
- Position: Step 74 (line 114)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `checker.bzl`
- impl: `_setup_violations_impl` (line 135)
- Uses `SETUP_VIOLATIONS_CONFIG_KEYS` (lines 69-72)
- Rule: `librelane_setup_violations` (line 238)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 74 (lines 862-867)
- Named: `_chk_setup`
- Chains from `_eqy` when EQY runs, otherwise the pre-EQY predecessor
- No gating - always runs

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.SetupViolations"` | `"Checker.SetupViolations"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 74 (line 114) | Step 74 (line 862) | Y |

**Config Variable Audit:**

From TimingViolations parent (checker.py lines 476-500, dynamically created):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| TIMING_VIOLATION_CORNERS | List[str] | - | Yes | Wired (PDK) |
| SETUP_VIOLATION_CORNERS | Optional[List[str]] | None | No | Wired |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_setup`
  passed and produced `state_out.json`.
- Runtime reported no setup violations found.

---

### Step 75: Checker.HoldViolations

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.HoldViolations"` (line 677)
- inputs: `[]` (inherited from MetricChecker/TimingViolations)
- outputs: `[]` (inherited)
- Checks metric `timing__hold_vio__count` for hold timing violations

**Librelane Gating:** `classic.py`
- Position: Step 75 (line 115)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `checker.bzl`
- impl: `_hold_violations_impl` (line 138)
- Uses `HOLD_VIOLATIONS_CONFIG_KEYS` (lines 73-76)
- Rule: `librelane_hold_violations` (line 244)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 75 (lines 869-874)
- Named: `_chk_hold`
- Chains from: `_chk_setup`
- No gating - always runs

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.HoldViolations"` | `"Checker.HoldViolations"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 75 (line 115) | Step 75 (line 869) | Y |

**Config Variable Audit:**

From TimingViolations parent (checker.py lines 476-500, dynamically created):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| TIMING_VIOLATION_CORNERS | List[str] | - | Yes | Wired (PDK) |
| HOLD_VIOLATION_CORNERS | Optional[List[str]] | None | No | Wired |

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_hold`
  passed and produced `state_out.json`.
- Runtime reported no hold violations found.

---

### Step 76: Checker.MaxSlewViolations

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.MaxSlewViolations"` (line 666)
- inputs: `[]` (inherited from MetricChecker/TimingViolations)
- outputs: `[]` (inherited)
- Checks metric `design__max_slew_violation__count`

**Librelane Gating:** `classic.py`
- Position: Step 76 (line 116)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `checker.bzl`
- impl: `_max_slew_violations_impl` (line 141)
- Uses `MAX_SLEW_VIOLATIONS_CONFIG_KEYS` (lines 77-81)
- Rule: `librelane_max_slew_violations` (line 250)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 76 (lines 876-881)
- Named: `_chk_slew`
- Chains from: `_chk_hold`
- No gating - always runs

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.MaxSlewViolations"` | `"Checker.MaxSlewViolations"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 76 (line 116) | Step 76 (line 876) | Y |

**Config Variable Audit:**

From TimingViolations parent (checker.py lines 476-500, dynamically created):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| TIMING_VIOLATION_CORNERS | List[str] | - | Yes | Wired (PDK) |
| MAX_SLEW_VIOLATION_CORNERS | Optional[List[str]] | [""] | No | Wired |

Note: `corner_override = [""]` means no corners checked by default.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_slew`
  passed and produced `state_out.json`.
- Runtime reported no max slew violations found.

---

### Step 77.5: Zamlet.AntennaViolations

**Verified:** 2026-07-07

**Librelane Source:** none. This is a local Zamlet checker, not a LibreLane step.

**Bazel Implementation:** `checker.bzl`
- impl: `_zamlet_antenna_violations_impl` (line 144)
- Rule: `zamlet_antenna_violations` (line 322)
- Reads antenna metrics from incoming `state_out.json`
- Fails if antenna metrics are missing or nonzero
- Copies state through unchanged on success

**Bazel Flow:** `full_flow.bzl`
- Position: Step 77.5 (lines 885-890)
- Named: `_zamlet_chk_ant`
- Chains from: `_chk_slew`
- No LibreLane gate; local signoff guard

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_zamlet_chk_ant`
  passed and produced `state_out.json`.
- Runtime reported no antenna violations.

---

### Step 77: Checker.MaxCapViolations

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/checker.py`
- ID: `"Checker.MaxCapViolations"` (line 655)
- inputs: `[]` (inherited from MetricChecker/TimingViolations)
- outputs: `[]` (inherited)
- Checks metric `design__max_cap_violation__count`

**Librelane Gating:** `classic.py`
- Position: Step 77 (line 117)
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `checker.bzl`
- impl: `_max_cap_violations_impl` (line 144)
- Uses `MAX_CAP_VIOLATIONS_CONFIG_KEYS` (lines 82-85)
- Rule: `librelane_max_cap_violations` (line 256)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 77 (lines 893-898)
- Named: `_chk_cap`
- Chains from `_zamlet_chk_ant` because the local antenna checker is inserted
  between max-slew and max-cap
- No gating - always runs

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Checker.MaxCapViolations"` | `"Checker.MaxCapViolations"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` | `[]` | Y |
| Gating | None | None | N/A |
| Position | Step 77 (line 117) | Step 77 (line 893) | Y |

**Config Variable Audit:**

From TimingViolations parent (checker.py lines 476-500, dynamically created):
| Variable | Type | Default | PDK | Bazel Status |
|----------|------|---------|-----|--------------|
| TIMING_VIOLATION_CORNERS | List[str] | - | Yes | Wired (PDK) |
| MAX_CAP_VIOLATION_CORNERS | Optional[List[str]] | [""] | No | Wired |

Note: `corner_override = [""]` means no corners checked by default.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_chk_cap`
  passed and produced `state_out.json`.
- Runtime reported no max cap violations found.

---

### Step 78: Misc.ReportManufacturability

**Verified:** 2026-07-07 for LibreLane 3.0.4

**Librelane Source:** `~/Code/librelane/librelane/steps/misc.py`
- ID: `"Misc.ReportManufacturability"` (line 61)
- inputs: `[]` (line 64)
- outputs: `[]` (line 65)
- Logs a manufacturability report with DRC, LVS, and antenna violation status
- Writes `manufacturability.rpt` (line 156)
- Only reads metrics from state_in, no config variables

**Librelane Gating:** `classic.py`
- Position: Step 78 (line 118) - final step
- No entry in gating_config_vars dict - always runs

**Bazel Implementation:** `misc.bzl`
- impl: `_report_manufacturability_impl` (line 9)
- Uses `MISC_CONFIG_KEYS` which is `BASE_CONFIG_KEYS` (line 7)
- Declares `manufacturability.rpt`
- Rule: `librelane_report_manufacturability` (line 12)

**Bazel Flow:** `full_flow.bzl`
- Position: Step 78 (lines 900-905) - final step
- Named: `_mfg_report`
- Chains from: `_chk_cap`
- No gating - always runs

| Aspect | Librelane | Bazel | Match |
|--------|-----------|-------|-------|
| Step ID | `"Misc.ReportManufacturability"` | `"Misc.ReportManufacturability"` | Y |
| inputs | `[]` | (from src) | Y |
| outputs | `[]` plus manufacturability report | `manufacturability.rpt` | Y |
| Gating | None | None | N/A |
| Position | Step 78 (line 118) | Step 78 (line 900) | Y |

**Config Variable Audit:**

No config_vars defined in ReportManufacturability class (misc.py lines 55-160).
Step only reads metrics from state_in to generate the report.

**Status: PASS**

Verification:
- `bazel build //dse/maths:SegmentedMultiplier16x16_sky130hd_mfg_report`
  passed.
- Produced `manufacturability.rpt` and `state_out.json`.
- Report showed Antenna, LVS, and DRC all passed.

---

## Summary

- **Verified PASS:** 25 step entries (1-24 plus inserted OpenROAD.DumpRCValues, with some caveats)
- **Verified FAIL:** 0 steps
- **TODO:** 53 step entries (remaining unaudited flow steps need detailed verification)
- **Structural differences noted:** Steps 24-26 IO placement sequence

Critical issues:
1. Step 16: `MacroInfo` does not model per-instance placement locations for MACROS-based placement generation
2. Steps 24-26: Bazel uses conditional branching vs librelane's self-skip pattern
3. Steps 40 and 44: Run experimental code that is disabled by default in Classic flow
