# Checker rules for validation steps

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# Config keys for each checker step
# All steps require BASE_CONFIG_KEYS for librelane's Config.load infrastructure.

# Step 2: Checker.LintTimingConstructs - checker.py lines 386-418
# Overrides run(), only reads state_in.metrics, ignores config_vars (librelane_issue)
# We still wire ERROR_ON_LINTER_TIMING_CONSTRUCTS because it's declared in config_vars
LINT_TIMING_CONSTRUCTS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_TIMING_CONSTRUCTS"]

# Step 3: Checker.LintErrors - checker.py lines 346-361
# Uses MetricChecker.run() which reads self.config.get("ERROR_ON_LINTER_ERRORS") at line 119
LINT_ERRORS_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LINTER_ERRORS"]

# Step 4: Checker.LintWarnings - checker.py lines 365-381
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
]

# Step 68: Checker.KLayoutDRC - checker.py lines 412-428
KLAYOUT_DRC_CHECKER_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "ERROR_ON_KLAYOUT_DRC",
]

# Step 70: Checker.IllegalOverlap - checker.py lines 216-231
# Uses MetricChecker.run() which reads self.config.get("ERROR_ON_ILLEGAL_OVERLAPS") at line 119
ILLEGAL_OVERLAP_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_ILLEGAL_OVERLAPS"]

# Step 72: Checker.LVS - checker.py lines 299-314
# Uses MetricChecker.run() which reads self.config.get("ERROR_ON_LVS_ERROR") at line 119
LVS_CHECKER_CONFIG_KEYS = BASE_CONFIG_KEYS + ["ERROR_ON_LVS_ERROR"]

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

def _setup_wns_threshold_impl(ctx):
    state_info = ctx.attr.src[LibrelaneInfo]
    state_out = ctx.actions.declare_file(ctx.label.name + "/state_out.json")

    ctx.actions.run_shell(
        inputs = [state_info.state_out],
        outputs = [state_out],
        command = """
            set -e
            cp "{src_state_out}" "{state_out}"

            setup_wns="$(jq -r '.metrics.timing__setup__ws // "missing"' "{src_state_out}")"
            if [ "$setup_wns" = "missing" ]; then
                echo "ERROR: Zamlet setup WNS checker could not find timing__setup__ws."
                exit 1
            fi

            if ! jq -n -e --arg wns "$setup_wns" --arg threshold "{threshold}" \
                '($wns | tonumber) >= ($threshold | tonumber)' >/dev/null; then
                echo "ERROR: setup WNS $setup_wns ns is below threshold {threshold} ns."
                exit 1
            fi

            echo "Setup WNS $setup_wns ns meets threshold {threshold} ns."
        """.format(
            src_state_out = state_info.state_out.path,
            state_out = state_out.path,
            threshold = ctx.attr.threshold,
        ),
    )

    return [
        DefaultInfo(files = depset([state_out])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = state_info.sdf,
            spef = state_info.spef,
            lib = state_info.lib,
            gds = state_info.gds,
            mag_gds = state_info.mag_gds,
            klayout_gds = state_info.klayout_gds,
            lef = state_info.lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

def _hold_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.HoldViolations", HOLD_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

def _max_slew_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.MaxSlewViolations", MAX_SLEW_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

def _max_cap_violations_impl(ctx):
    return single_step_impl(ctx, "Checker.MaxCapViolations", MAX_CAP_VIOLATIONS_CONFIG_KEYS, step_outputs = [])

def _zamlet_antenna_violations_impl(ctx):
    state_info = ctx.attr.src[LibrelaneInfo]
    state_out = ctx.actions.declare_file(ctx.label.name + "/state_out.json")

    ctx.actions.run_shell(
        inputs = [state_info.state_out],
        outputs = [state_out],
        command = """
            set -e
            echo "Zamlet local antenna violations checker (not a LibreLane step)."
            mkdir -p "$(dirname "{state_out}")"
            cp "{src_state_out}" "{state_out}"

            route_count="$(jq -r '.metrics.route__antenna_violation__count // "missing"' "{src_state_out}")"
            nets_count="$(jq -r '.metrics.antenna__violating__nets // .metrics.route__antenna_violation__count // "missing"' "{src_state_out}")"
            pins_count="$(jq -r '.metrics.antenna__violating__pins // 0' "{src_state_out}")"

            if [ "$route_count" = "missing" ] || [ "$nets_count" = "missing" ]; then
                echo "ERROR: Zamlet local antenna checker could not find antenna metrics."
                echo "Expected route__antenna_violation__count from OpenROAD.CheckAntennas."
                exit 1
            fi

            if [ "$route_count" != "0" ] || [ "$nets_count" != "0" ] || [ "$pins_count" != "0" ]; then
                echo "ERROR: Zamlet local antenna checker found antenna violations."
                echo "  route__antenna_violation__count: $route_count"
                echo "  antenna__violating__nets: $nets_count"
                echo "  antenna__violating__pins: $pins_count"
                exit 1
            fi

            echo "Zamlet local antenna checker found no antenna violations."
        """.format(
            src_state_out = state_info.state_out.path,
            state_out = state_out.path,
        ),
    )

    return [
        DefaultInfo(files = depset([state_out])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = state_info.sdf,
            spef = state_info.spef,
            lib = state_info.lib,
            gds = state_info.gds,
            mag_gds = state_info.mag_gds,
            klayout_gds = state_info.klayout_gds,
            lef = state_info.lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

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

zamlet_setup_wns_threshold = rule(
    implementation = _setup_wns_threshold_impl,
    attrs = dict(FLOW_ATTRS, **{
        "threshold": attr.string(
            doc = "Minimum allowed setup WNS in ns.",
            default = "0",
        ),
    }),
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

# Local Zamlet checker. This intentionally is not a LibreLane step; it fails the
# Bazel signoff chain on antenna metrics produced by OpenROAD.CheckAntennas.
zamlet_antenna_violations = rule(
    implementation = _zamlet_antenna_violations_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
