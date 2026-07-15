# Placement rules

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "single_step_impl",
    "FLOW_ATTRS",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
    "BASE_CONFIG_KEYS",
    "OPENROAD_STEP_CONFIG_KEYS",
)

# Placement steps need BASE_CONFIG_KEYS for PDK info and design config
PLACE_CONFIG_KEYS = BASE_CONFIG_KEYS

MANUAL_MACRO_PLACEMENT_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "MACROS",
    "EXTRA_LEFS",
    "MACRO_PLACEMENT_CFG",
]

# ResizerStep config keys (used by RepairDesignPostGPL, ResizerTimingPostCTS, etc.)
# Includes: OpenROADStep.config_vars + grt_variables + rsz_variables
RESIZER_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
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
    # rsz_variables specific (common_variables.py:321-340)
    "RSZ_DONT_TOUCH_RX",
    "RSZ_DONT_TOUCH_LIST",
    "RSZ_CORNERS",
]

# ResizerTimingPostCTS/PostGRT config keys (ResizerStep + own config_vars)
RESIZER_TIMING_CONFIG_KEYS = RESIZER_CONFIG_KEYS + [
    "PL_RESIZER_HOLD_SLACK_MARGIN",
    "PL_RESIZER_SETUP_SLACK_MARGIN",
    "PL_RESIZER_HOLD_MAX_BUFFER_PCT",
    "PL_RESIZER_SETUP_MAX_BUFFER_PCT",
    "PL_RESIZER_ALLOW_SETUP_VIOS",
    "PL_RESIZER_SETUP_GATE_CLONING",
    "PL_RESIZER_SETUP_BUFFERING",
    "PL_RESIZER_SETUP_BUFFER_REMOVAL",
    "PL_RESIZER_SETUP_REPAIR_TNS_PCT",
    "PL_RESIZER_SETUP_MAX_UTIL_PCT",
    "PL_RESIZER_HOLD_REPAIR_TNS_PCT",
    "PL_RESIZER_HOLD_MAX_UTIL_PCT",
    "PL_RESIZER_FIX_HOLD_FIRST",
]

# RepairDesignPostGPL config keys (ResizerStep + own config_vars)
REPAIR_DESIGN_CONFIG_KEYS = RESIZER_CONFIG_KEYS + [
    "DESIGN_REPAIR_BUFFER_INPUT_PORTS",
    "DESIGN_REPAIR_BUFFER_OUTPUT_PORTS",
    "DESIGN_REPAIR_TIE_FANOUT",
    "DESIGN_REPAIR_TIE_SEPARATION",
    "DESIGN_REPAIR_MAX_WIRE_LENGTH",
    "DESIGN_REPAIR_MAX_SLEW_PCT",
    "DESIGN_REPAIR_MAX_CAP_PCT",
    "DESIGN_REPAIR_REMOVE_BUFFERS",
]

# DetailedPlacement config keys (OpenROADStep.config_vars + dpl_variables)
DPL_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # dpl_variables (common_variables.py:255-283)
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
]

# OpenROAD.CTS config keys (OpenROADStep.config_vars + dpl_variables + CTS-specific)
CTS_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # dpl_variables (common_variables.py:255-283) - CTS calls dpl.tcl
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
    # CTS-specific config_vars (openroad.py:2016-2084)
    "CTS_BALANCE_LEVELS",
    "CTS_SINK_BUFFER_MAX_CAP_DERATE_PCT",
    "CTS_DELAY_BUFFER_DERATE_PCT",
    "CTS_OBSTRUCTION_AWARE",
    "CTS_SINK_CLUSTERING_ENABLE",
    "CTS_SINK_CLUSTERING_SIZE",
    "CTS_SINK_CLUSTERING_MAX_DIAMETER",
    "CTS_MACRO_CLUSTERING_SIZE",
    "CTS_MACRO_CLUSTERING_MAX_DIAMETER",
    "CTS_CLK_MAX_WIRE_LENGTH",
    "CTS_DISABLE_POST_PROCESSING",
    "CTS_DISTANCE_BETWEEN_BUFFERS",
    "CTS_CORNERS",
    "CTS_ROOT_BUFFER",
    "CTS_CLK_BUFFERS",
    "CTS_MAX_CAP",
    "CTS_MAX_SLEW",
    "CTS_APPLY_NDR",
]

# IOPlacement config keys (io_layer_variables + IOPlacement-specific)
IO_PLACEMENT_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "IO_PIN_V_EXTENSION",
    "IO_PIN_H_EXTENSION",
    "IO_PIN_V_THICKNESS_MULT",
    "IO_PIN_H_THICKNESS_MULT",
    "IO_PIN_H_LAYER",
    "IO_PIN_V_LAYER",
    "IO_PIN_PLACEMENT_MODE",
    "IO_PIN_MIN_DISTANCE",
    "IO_PIN_ORDER_CFG",
    "IO_PIN_V_LENGTH",
    "IO_PIN_H_LENGTH",
    "FP_DEF_TEMPLATE",
]

# CustomIOPlacement config keys (io_layer_variables + CustomIOPlacement-specific)
CUSTOM_IO_PLACEMENT_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "IO_PIN_V_EXTENSION",
    "IO_PIN_H_EXTENSION",
    "IO_PIN_V_THICKNESS_MULT",
    "IO_PIN_H_THICKNESS_MULT",
    "IO_PIN_V_LENGTH",
    "IO_PIN_H_LENGTH",
    "IO_PIN_ORDER_CFG",
    "IO_PIN_H_LAYER",
    "IO_PIN_V_LAYER",
    "ERRORS_ON_UNMATCHED_IO",
]

# ApplyDEFTemplate config keys (odb.py lines 243-259)
APPLY_DEF_TEMPLATE_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "FP_DEF_TEMPLATE",
    "FP_TEMPLATE_MATCH_MODE",
    "FP_TEMPLATE_COPY_POWER_PINS",
]

# OpenROAD.CutRows config keys
CUTROWS_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "FP_MACRO_HORIZONTAL_HALO",
    "FP_MACRO_VERTICAL_HALO",
    "FP_PRUNE_THRESHOLD",
]

# OpenROAD.TapEndcapInsertion config keys
TAP_ENDCAP_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "FP_MACRO_HORIZONTAL_HALO",
    "FP_MACRO_VERTICAL_HALO",
    "FP_TAPCELL_DIST",
]

# _GlobalPlacement base config keys (OpenROADStep + routing/placement/resizer vars)
_GPL_BASE_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "PL_TARGET_DENSITY_PCT",
    "PL_SKIP_INITIAL_PLACEMENT",
    "PL_WIRE_LENGTH_COEF",
    "PL_MIN_PHI_COEFFICIENT",
    "PL_MAX_PHI_COEFFICIENT",
    "FP_CORE_UTIL",
    "GPL_CELL_PADDING",
    "PL_KEEP_RESIZE_BELOW_OVERFLOW",
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
    "RSZ_DONT_TOUCH_RX",
    "RSZ_DONT_TOUCH_LIST",
    "RSZ_CORNERS",
]

# GlobalPlacementSkipIO config keys (_GlobalPlacement + skip conditions)
GPL_SKIP_IO_CONFIG_KEYS = _GPL_BASE_CONFIG_KEYS + [
    "IO_PIN_PLACEMENT_MODE",
    "IO_PIN_ORDER_CFG",
    "FP_DEF_TEMPLATE",
]

# GlobalPlacement config keys (_GlobalPlacement + time/routability vars)
GPL_CONFIG_KEYS = _GPL_BASE_CONFIG_KEYS + [
    "PL_TIMING_DRIVEN",
    "PL_ROUTABILITY_DRIVEN",
    "PL_ROUTABILITY_OVERFLOW_THRESHOLD",
]

# OpenROAD.GeneratePDN config keys (pdn_variables from common_variables.py)
PDN_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # User-configurable
    "PDN_SKIPTRIM",
    "PDN_CORE_RING",
    "PDN_ENABLE_RAILS",
    "PDN_HORIZONTAL_HALO",
    "PDN_VERTICAL_HALO",
    "PDN_MULTILAYER",
    "PDN_CFG",
    # PDK-level (from pdk provider)
    "PDN_RAIL_LAYER",
    "PDN_RAIL_WIDTH",
    "PDN_RAIL_OFFSET",
    "PDN_HORIZONTAL_LAYER",
    "PDN_VERTICAL_LAYER",
    "PDN_CORE_HORIZONTAL_LAYER",
    "PDN_CORE_VERTICAL_LAYER",
    "PDN_HOFFSET",
    "PDN_VOFFSET",
    "PDN_HPITCH",
    "PDN_VPITCH",
    "PDN_HSPACING",
    "PDN_VSPACING",
    "PDN_HWIDTH",
    "PDN_VWIDTH",
    "PDN_CORE_RING_HOFFSET",
    "PDN_CORE_RING_VOFFSET",
    "PDN_CORE_RING_HSPACING",
    "PDN_CORE_RING_VSPACING",
    "PDN_CORE_RING_HWIDTH",
    "PDN_CORE_RING_VWIDTH",
    "PDN_CORE_RING_CONNECT_TO_PADS",
    "PDN_CORE_RING_ALLOW_OUT_OF_DIE",
    "PDN_EXTEND_TO",
    "PDN_ENABLE_PINS",
]

def _macro_placement_impl(ctx):
    extra = {
        "PL_MACRO_HALO": ctx.attr.macro_halo,
        "PL_MACRO_CHANNEL": ctx.attr.macro_channel,
    }
    return single_step_impl(ctx, "OpenROAD.BasicMacroPlacement", PLACE_CONFIG_KEYS,
        step_outputs = ["def", "odb"], extra_config = extra)

def _manual_macro_placement_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.macro_placement_cfg else []
    return single_step_impl(ctx, "Odb.ManualMacroPlacement", MANUAL_MACRO_PLACEMENT_CONFIG_KEYS,
        step_outputs = step_outputs)

def _cut_rows_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.CutRows", CUTROWS_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _tap_endcap_insertion_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.TapEndcapInsertion", TAP_ENDCAP_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _generate_pdn_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.GeneratePDN", PDN_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _global_placement_skip_io_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = [] if input_info.fp_def_template or input_info.io_pin_order_cfg else ["def", "odb", "nl", "pnl", "sdc"]
    return single_step_impl(ctx, "OpenROAD.GlobalPlacementSkipIO", GPL_SKIP_IO_CONFIG_KEYS,
        step_outputs = step_outputs)

def _io_placement_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = [] if input_info.io_pin_order_cfg or input_info.fp_def_template else ["def", "odb"]
    return single_step_impl(ctx, "OpenROAD.IOPlacement", IO_PLACEMENT_CONFIG_KEYS,
        step_outputs = step_outputs)

def _custom_io_placement_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.io_pin_order_cfg else []
    return single_step_impl(ctx, "Odb.CustomIOPlacement", CUSTOM_IO_PLACEMENT_CONFIG_KEYS,
        step_outputs = step_outputs)

def _apply_def_template_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.fp_def_template else []
    return single_step_impl(ctx, "Odb.ApplyDEFTemplate", APPLY_DEF_TEMPLATE_CONFIG_KEYS,
        step_outputs = step_outputs)

def _global_placement_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.GlobalPlacement", GPL_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _repair_design_post_gpl_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.RepairDesignPostGPL", REPAIR_DESIGN_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _detailed_placement_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.DetailedPlacement", DPL_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _cts_impl(ctx):
    """Clock tree synthesis with CTS report.

    CTS adds clock buffers to the design, modifying the netlist.
    We must capture the updated nl/pnl/sdc along with def/odb.
    """
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # Declare all OpenROAD outputs plus CTS report
    def_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".def")
    odb_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".odb")
    nl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".nl.v")
    pnl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".pnl.v")
    sdc_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".sdc")
    cts_report = ctx.actions.declare_file(ctx.label.name + "/cts.rpt")

    # Get input files
    inputs = get_input_files(input_info, state_info, CTS_CONFIG_KEYS)

    # Create config with CTS options (all via LibrelaneInput, no step-local attrs)
    config = create_librelane_config(input_info, state_info, CTS_CONFIG_KEYS)

    # Run CTS with all outputs
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.CTS",
        outputs = [def_out, odb_out, nl_out, pnl_out, sdc_out, cts_report],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset([def_out, odb_out, nl_out, pnl_out, sdc_out, cts_report, state_out])),
        LibrelaneInfo(
            state_out = state_out,
            nl = nl_out,
            pnl = pnl_out,
            odb = odb_out,
            sdc = sdc_out,
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
            **{"def": def_out}
        ),
    ]

def _resizer_timing_post_cts_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.ResizerTimingPostCTS", RESIZER_TIMING_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])


_macro_placement_attrs = dict(FLOW_ATTRS, **{
    "macro_halo": attr.string(
        doc = "Macro placement halo '{Horizontal} {Vertical}' in µm",
        default = "10 10",
    ),
    "macro_channel": attr.string(
        doc = "Channel widths between macros '{Horizontal} {Vertical}' in µm",
        default = "20 20",
    ),
})

librelane_macro_placement = rule(
    implementation = _macro_placement_impl,
    attrs = _macro_placement_attrs,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_manual_macro_placement = rule(
    implementation = _manual_macro_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_cut_rows = rule(
    implementation = _cut_rows_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_tap_endcap_insertion = rule(
    implementation = _tap_endcap_insertion_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_generate_pdn = rule(
    implementation = _generate_pdn_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_global_placement_skip_io = rule(
    implementation = _global_placement_skip_io_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_io_placement = rule(
    implementation = _io_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_custom_io_placement = rule(
    implementation = _custom_io_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_apply_def_template = rule(
    implementation = _apply_def_template_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_global_placement = rule(
    implementation = _global_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_repair_design_post_gpl = rule(
    implementation = _repair_design_post_gpl_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_detailed_placement = rule(
    implementation = _detailed_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_cts = rule(
    implementation = _cts_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_resizer_timing_post_cts = rule(
    implementation = _resizer_timing_post_cts_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
