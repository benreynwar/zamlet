# Checker rules for validation steps

load(":common.bzl", "single_step_impl", "FLOW_ATTRS")
load(":providers.bzl", "LibrelaneInfo")

def _lint_timing_constructs_impl(ctx):
    return single_step_impl(ctx, "Checker.LintTimingConstructs", step_outputs = [])

def _lint_errors_impl(ctx):
    return single_step_impl(ctx, "Checker.LintErrors", step_outputs = [])

def _lint_warnings_impl(ctx):
    return single_step_impl(ctx, "Checker.LintWarnings", step_outputs = [])

def _yosys_unmapped_cells_impl(ctx):
    return single_step_impl(ctx, "Checker.YosysUnmappedCells", step_outputs = [])

def _yosys_synth_checks_impl(ctx):
    return single_step_impl(ctx, "Checker.YosysSynthChecks", step_outputs = [])

def _netlist_assign_statements_impl(ctx):
    return single_step_impl(ctx, "Checker.NetlistAssignStatements", step_outputs = [])

def _power_grid_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.PowerGridViolations", step_outputs = [])

def _tr_drc_impl(ctx):
    return single_step_impl(ctx, "Checker.TrDRC", step_outputs = [])

def _disconnected_pins_impl(ctx):
    return single_step_impl(ctx, "Checker.DisconnectedPins", step_outputs = [])

def _wire_length_impl(ctx):
    return single_step_impl(ctx, "Checker.WireLength", step_outputs = [])

def _xor_impl(ctx):
    return single_step_impl(ctx, "Checker.XOR", step_outputs = [])

def _magic_drc_impl(ctx):
    return single_step_impl(ctx, "Checker.MagicDRC", step_outputs = [])

def _klayout_drc_impl(ctx):
    return single_step_impl(ctx, "Checker.KLayoutDRC", step_outputs = [])

def _illegal_overlap_impl(ctx):
    return single_step_impl(ctx, "Checker.IllegalOverlap", step_outputs = [])

def _lvs_impl(ctx):
    return single_step_impl(ctx, "Checker.LVS", step_outputs = [])

def _setup_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.SetupViolations", step_outputs = [])

def _hold_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.HoldViolations", step_outputs = [])

def _max_slew_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.MaxSlewViolations", step_outputs = [])

def _max_cap_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.MaxCapViolations", step_outputs = [])

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
