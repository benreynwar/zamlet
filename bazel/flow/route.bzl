# Routing rules

load(":providers.bzl", "LibrelaneInfo", "LibrelaneInput")
load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "OPENROAD_STEP_CONFIG_KEYS")

# GlobalRouting config keys (OpenROADStep + grt_variables + dpl_variables)
GRT_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # routing_layer_variables (common_variables.py:223-252)
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
    # grt_variables specific (common_variables.py:285-319)
    "DIODE_PADDING",
    "GRT_ALLOW_CONGESTION",
    "GRT_ANTENNA_REPAIR_ITERS",
    "GRT_OVERFLOW_ITERS",
    "GRT_ANTENNA_REPAIR_MARGIN",
    "GRT_ANTENNA_REPAIR_JUMPER_ONLY",
    "GRT_ANTENNA_REPAIR_DIODE_ONLY",
    # dpl_variables (common_variables.py:255-283)
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
]

# CheckAntennas only needs OpenROADStep config_vars (openroad.py:1381-1396)
CHECK_ANTENNAS_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS

# ResizerStep config_vars = OpenROADStep + grt_variables + rsz_variables (openroad.py:1971)
RESIZER_STEP_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # grt_variables = routing_layer_variables + grt-specific (common_variables.py:285-319)
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
    "DIODE_PADDING",
    "GRT_ALLOW_CONGESTION",
    "GRT_ANTENNA_REPAIR_ITERS",
    "GRT_OVERFLOW_ITERS",
    "GRT_ANTENNA_REPAIR_MARGIN",
    "GRT_ANTENNA_REPAIR_JUMPER_ONLY",
    "GRT_ANTENNA_REPAIR_DIODE_ONLY",
    # rsz_variables = dpl_variables + rsz-specific (common_variables.py:321-340)
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
    "RSZ_DONT_TOUCH_RX",
    "RSZ_DONT_TOUCH_LIST",
    "RSZ_CORNERS",
]

# RepairDesignPostGRT config_vars = ResizerStep + 4 step-specific (openroad.py:2649-2684)
REPAIR_DESIGN_POST_GRT_CONFIG_KEYS = RESIZER_STEP_CONFIG_KEYS + [
    "GRT_DESIGN_REPAIR_RUN_GRT",
    "GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH",
    "GRT_DESIGN_REPAIR_MAX_SLEW_PCT",
    "GRT_DESIGN_REPAIR_MAX_CAP_PCT",
]

# Placeholder for steps not yet audited (TODO: create step-specific CONFIG_KEYS)
ROUTE_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS

def _global_routing_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.GlobalRouting", GRT_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _check_antennas_impl(ctx):
    return single_step_impl(
        ctx, "OpenROAD.CheckAntennas", CHECK_ANTENNAS_CONFIG_KEYS,
        step_outputs = [],
        extra_outputs = ["reports/antenna.rpt", "reports/antenna_summary.rpt"],
    )

def _repair_design_post_grt_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.RepairDesignPostGRT", REPAIR_DESIGN_POST_GRT_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

# RepairAntennas is CompositeStep containing _DiodeInsertion (GlobalRouting) + CheckAntennas
# _DiodeInsertion.config_vars = GlobalRouting.config_vars = OpenROADStep + grt_variables + dpl_variables
# CheckAntennas.config_vars = OpenROADStep.config_vars (no additional)
# Union = GRT_CONFIG_KEYS (DIODE_CELL is in BASE_CONFIG_KEYS)
REPAIR_ANTENNAS_CONFIG_KEYS = GRT_CONFIG_KEYS

def _repair_antennas_impl(ctx):
    if ctx.attr.input[LibrelaneInput].pdk_info.diode_cell == None:
        return [
            DefaultInfo(files = ctx.attr.src[DefaultInfo].files),
            ctx.attr.src[LibrelaneInfo],
        ]

    return single_step_impl(ctx, "OpenROAD.RepairAntennas", REPAIR_ANTENNAS_CONFIG_KEYS,
        step_outputs = ["def", "odb"], output_subdir = "1-openroad-diodeinsertion")

# ResizerTimingPostGRT config_vars = ResizerStep + step-specific (openroad.py:2805-2869)
RESIZER_TIMING_POST_GRT_CONFIG_KEYS = RESIZER_STEP_CONFIG_KEYS + [
    "GRT_RESIZER_HOLD_SLACK_MARGIN",
    "GRT_RESIZER_SETUP_SLACK_MARGIN",
    "GRT_RESIZER_HOLD_MAX_BUFFER_PCT",
    "GRT_RESIZER_SETUP_MAX_BUFFER_PCT",
    "GRT_RESIZER_ALLOW_SETUP_VIOS",
    "GRT_RESIZER_SETUP_GATE_CLONING",
    "GRT_RESIZER_RUN_GRT",
    "GRT_RESIZER_SETUP_BUFFERING",
    "GRT_RESIZER_SETUP_BUFFER_REMOVAL",
    "GRT_RESIZER_SETUP_REPAIR_TNS_PCT",
    "GRT_RESIZER_SETUP_MAX_UTIL_PCT",
    "GRT_RESIZER_HOLD_REPAIR_TNS_PCT",
    "GRT_RESIZER_HOLD_MAX_UTIL_PCT",
    "GRT_RESIZER_FIX_HOLD_FIRST",
]

def _resizer_timing_post_grt_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.ResizerTimingPostGRT", RESIZER_TIMING_POST_GRT_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

# DetailedRouting config_vars = OpenROADStep + grt_variables + step-specific (openroad.py:1931-1993)
DETAILED_ROUTING_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # grt_variables
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
    "DIODE_PADDING",
    "GRT_ALLOW_CONGESTION",
    "GRT_ANTENNA_REPAIR_ITERS",
    "GRT_OVERFLOW_ITERS",
    "GRT_ANTENNA_REPAIR_MARGIN",
    "GRT_ANTENNA_REPAIR_JUMPER_ONLY",
    "GRT_ANTENNA_REPAIR_DIODE_ONLY",
    # DetailedRouting-specific
    "DRT_THREADS",
    "DRT_OPT_ITERS",
    "DRT_SAVE_SNAPSHOTS",
    "DRT_ANTENNA_REPAIR_ITERS",
    "DRT_ANTENNA_REPAIR_MARGIN",
    "DRT_ANTENNA_REPAIR_JUMPER_ONLY",
    "DRT_ANTENNA_REPAIR_DIODE_ONLY",
    "DRT_SAVE_DRC_REPORT_ITERS",
    "NON_DEFAULT_RULES",
    "DRT_ASSIGN_NDR",
]

def _detailed_routing_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.DetailedRouting", DETAILED_ROUTING_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

librelane_global_routing = rule(
    implementation = _global_routing_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_check_antennas = rule(
    implementation = _check_antennas_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_repair_design_post_grt = rule(
    implementation = _repair_design_post_grt_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_repair_antennas = rule(
    implementation = _repair_antennas_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_resizer_timing_post_grt = rule(
    implementation = _resizer_timing_post_grt_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_detailed_routing = rule(
    implementation = _detailed_routing_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
