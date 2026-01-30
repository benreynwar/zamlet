# Checker rules for validation steps

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# Config keys for each checker step
# All steps require BASE_CONFIG_KEYS for librelane's Config.load infrastructure.

# Step 2: Checker.LintTimingConstructs - checker.py lines 376-409
# Overrides run(), only reads state_in.metrics, ignores config_vars (librelane_issue)
# We still wire ERROR_ON_LINTER_TIMING_CONSTRUCTS because it's declared in config_vars
LINT_TIMING_CONSTRUCTS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_TIMING_CONSTRUCTS"]

# Step 3: Checker.LintErrors - checker.py lines 336-352
# Uses MetricChecker.run() which reads self.config.get("ERROR_ON_LINTER_ERRORS") at line 119
LINT_ERRORS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_ERRORS"]

# Step 4: Checker.LintWarnings - checker.py lines 356-372
# Uses MetricChecker.run() which reads self.config.get("ERROR_ON_LINTER_WARNINGS") at line 119
LINT_WARNINGS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_WARNINGS"]

# Step 7: Checker.YosysUnmappedCells - checker.py lines 141-156
YOSYS_UNMAPPED_CELLS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_UNMAPPED_CELLS"]

# Step 8: Checker.YosysSynthChecks - checker.py lines 159-174
YOSYS_SYNTH_CHECKS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_SYNTH_CHECKS"]

# Step 9: Checker.NetlistAssignStatements - checker.py lines 30-66
NETLIST_ASSIGN_STATEMENTS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_NL_ASSIGN_STATEMENTS"]

# Step 29: Checker.PowerGridViolations - checker.py lines 318-332
POWER_GRID_VIOLATIONS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_PDN_VIOLATIONS"]

# Step 49: Checker.TrDRC - checker.py lines 178-193
TR_DRC_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_TR_DRC"]

# Step 51: Checker.DisconnectedPins - checker.py lines 235-250
DISCONNECTED_PINS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_DISCONNECTED_PINS"]

# Step 53: Checker.WireLength - checker.py lines 254-276
WIRE_LENGTH_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LONG_WIRE", "WIRE_LENGTH_THRESHOLD"]

# Step 64: Checker.XOR - checker.py lines 280-295
XOR_CHECKER_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_XOR_ERROR"]

# Step 67: Checker.MagicDRC - checker.py lines 197-212
MAGIC_DRC_CHECKER_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "ERROR_ON_MAGIC_DRC",
    "RUN_MAGIC_DRC",  # Gating (classic.py:293)
]

# Step 68: Checker.KLayoutDRC - checker.py lines 412-428
KLAYOUT_DRC_CHECKER_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "ERROR_ON_KLAYOUT_DRC",
    "RUN_KLAYOUT_DRC",  # Gating (classic.py:300)
]

# Step 70: Checker.IllegalOverlap - checker.py lines 216-231
# Uses MetricChecker.run() which reads self.config.get("ERROR_ON_ILLEGAL_OVERLAPS") at line 119
ILLEGAL_OVERLAP_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_ILLEGAL_OVERLAPS"]

# Step 72: Checker.LVS - checker.py lines 299-314
# Uses MetricChecker.run() which reads self.config.get("ERROR_ON_LVS_ERROR") at line 119
# Also gated by RUN_LVS (same as Netgen.LVS)
LVS_CHECKER_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LVS_ERROR", "RUN_LVS"]

# Steps 74-77: TimingViolations checkers - checker.py lines 431-637
# All inherit from TimingViolations which adds TIMING_VIOLATION_CORNERS (PDK) and
# a subclass-specific *_VIOLATION_CORNERS variable
SETUP_VIOLATIONS_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "TIMING_VIOLATION_CORNERS",
    "SETUP_VIOLATION_CORNERS",
]
HOLD_VIOLATIONS_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "TIMING_VIOLATION_CORNERS",
    "HOLD_VIOLATION_CORNERS",
]
MAX_SLEW_VIOLATIONS_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "TIMING_VIOLATION_CORNERS",
    "MAX_SLEW_VIOLATION_CORNERS",
]
MAX_CAP_VIOLATIONS_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "TIMING_VIOLATION_CORNERS",
    "MAX_CAP_VIOLATION_CORNERS",
]

# TODO: Add proper config keys for remaining checker steps
CHECKER_CONFIG_KEYS = BASE_CONFIG_KEYS

def _lint_timing_constructs_impl(ctx):
    return single_step_impl(ctx, "Checker.LintTimingConstructs", LINT_TIMING_CONSTRUCTS_CONFIG_KEYS, step_outputs = [])

def _lint_errors_impl(ctx):
    return single_step_impl(ctx, "Checker.LintErrors", LINT_ERRORS_CONFIG_KEYS, step_outputs = [])

def _lint_warnings_impl(ctx):
    return single_step_impl(ctx, "Checker.LintWarnings", LINT_WARNINGS_CONFIG_KEYS, step_outputs = [])

def _yosys_unmapped_cells_impl(ctx):
    return single_step_impl(ctx, "Checker.YosysUnmappedCells", YOSYS_UNMAPPED_CELLS_CONFIG_KEYS, step_outputs = [])

def _yosys_synth_checks_impl(ctx):
    return single_step_impl(ctx, "Checker.YosysSynthChecks", YOSYS_SYNTH_CHECKS_CONFIG_KEYS, step_outputs = [])

def _netlist_assign_statements_impl(ctx):
    return single_step_impl(ctx, "Checker.NetlistAssignStatements", NETLIST_ASSIGN_STATEMENTS_CONFIG_KEYS, step_outputs = [])

def _power_grid_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.PowerGridViolations", POWER_GRID_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

def _tr_drc_impl(ctx):
    return single_step_impl(ctx, "Checker.TrDRC", TR_DRC_CONFIG_KEYS, step_outputs = [])

def _disconnected_pins_impl(ctx):
    return single_step_impl(ctx, "Checker.DisconnectedPins", DISCONNECTED_PINS_CONFIG_KEYS, step_outputs = [])

def _wire_length_impl(ctx):
    return single_step_impl(ctx, "Checker.WireLength", WIRE_LENGTH_CONFIG_KEYS, step_outputs = [])

def _xor_impl(ctx):
    return single_step_impl(ctx, "Checker.XOR", XOR_CHECKER_CONFIG_KEYS, step_outputs = [])

def _magic_drc_impl(ctx):
    return single_step_impl(ctx, "Checker.MagicDRC", MAGIC_DRC_CHECKER_CONFIG_KEYS, step_outputs = [])

def _klayout_drc_impl(ctx):
    return single_step_impl(ctx, "Checker.KLayoutDRC", KLAYOUT_DRC_CHECKER_CONFIG_KEYS, step_outputs = [])

def _illegal_overlap_impl(ctx):
    return single_step_impl(ctx, "Checker.IllegalOverlap", ILLEGAL_OVERLAP_CONFIG_KEYS, step_outputs = [])

def _lvs_impl(ctx):
    return single_step_impl(ctx, "Checker.LVS", LVS_CHECKER_CONFIG_KEYS, step_outputs = [])

def _setup_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.SetupViolations", SETUP_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

def _hold_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.HoldViolations", HOLD_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

def _max_slew_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.MaxSlewViolations", MAX_SLEW_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

def _max_cap_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.MaxCapViolations", MAX_CAP_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

# Rule declarations
librelane_lint_timing_constructs = rule(
    implementation = _lint_timing_constructs_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_lint_errors = rule(
    implementation = _lint_errors_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_lint_warnings = rule(
    implementation = _lint_warnings_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_yosys_unmapped_cells = rule(
    implementation = _yosys_unmapped_cells_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_yosys_synth_checks = rule(
    implementation = _yosys_synth_checks_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_netlist_assign_statements = rule(
    implementation = _netlist_assign_statements_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_power_grid_violations = rule(
    implementation = _power_grid_violations_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_tr_drc = rule(
    implementation = _tr_drc_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_disconnected_pins = rule(
    implementation = _disconnected_pins_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_wire_length = rule(
    implementation = _wire_length_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_xor = rule(
    implementation = _xor_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_magic_drc_checker = rule(
    implementation = _magic_drc_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_klayout_drc_checker = rule(
    implementation = _klayout_drc_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_illegal_overlap = rule(
    implementation = _illegal_overlap_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_lvs_checker = rule(
    implementation = _lvs_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_setup_violations = rule(
    implementation = _setup_violations_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_hold_violations = rule(
    implementation = _hold_violations_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_max_slew_violations = rule(
    implementation = _max_slew_violations_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_max_cap_violations = rule(
    implementation = _max_cap_violations_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
