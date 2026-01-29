# Placement rules

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "single_step_impl",
    "FLOW_ATTRS",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
    "BASE_CONFIG_KEYS",
)

# Placement steps need BASE_CONFIG_KEYS for PDK info and design config
PLACE_CONFIG_KEYS = BASE_CONFIG_KEYS

# ResizerStep config keys (used by RepairDesignPostGPL, ResizerTimingPostCTS, etc.)
# Includes: OpenROADStep.config_vars + grt_variables + rsz_variables
RESIZER_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # OpenROADStep.config_vars (openroad.py:192-223)
    "PDN_CONNECT_MACROS_TO_GRID",
    "PDN_MACRO_CONNECTIONS",
    "PDN_ENABLE_GLOBAL_CONNECTIONS",
    "PNR_SDC_FILE",
    "FP_DEF_TEMPLATE",
    # OpenROADStep.prepare_env() (openroad.py:242-258)
    "FALLBACK_SDC_FILE",
    "EXTRA_EXCLUDED_CELLS",
    # routing_layer_variables (common_variables.py:223-252)
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
    # grt_variables specific (common_variables.py:285-319)
    "DIODE_PADDING",
    "GRT_ALLOW_CONGESTION",
    "GRT_ANTENNA_ITERS",
    "GRT_OVERFLOW_ITERS",
    "GRT_ANTENNA_MARGIN",
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
    "PL_RESIZER_GATE_CLONING",
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
DPL_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # OpenROADStep.config_vars (openroad.py:192-223)
    "PDN_CONNECT_MACROS_TO_GRID",
    "PDN_MACRO_CONNECTIONS",
    "PDN_ENABLE_GLOBAL_CONNECTIONS",
    "PNR_SDC_FILE",
    "FP_DEF_TEMPLATE",
    # OpenROADStep.prepare_env() (openroad.py:242-258)
    "FALLBACK_SDC_FILE",
    "EXTRA_EXCLUDED_CELLS",
    # dpl_variables (common_variables.py:255-283)
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
]

# OpenROAD.CTS config keys (OpenROADStep.config_vars + dpl_variables + CTS-specific)
CTS_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # OpenROADStep.config_vars (openroad.py:192-223)
    "PDN_CONNECT_MACROS_TO_GRID",
    "PDN_MACRO_CONNECTIONS",
    "PDN_ENABLE_GLOBAL_CONNECTIONS",
    "PNR_SDC_FILE",
    "FP_DEF_TEMPLATE",
    # OpenROADStep.prepare_env() (openroad.py:242-258)
    "FALLBACK_SDC_FILE",
    "EXTRA_EXCLUDED_CELLS",
    # dpl_variables (common_variables.py:255-283) - CTS calls dpl.tcl
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
    # CTS-specific config_vars (openroad.py:2016-2084)
    "CTS_SINK_CLUSTERING_SIZE",
    "CTS_SINK_CLUSTERING_MAX_DIAMETER",
    "CTS_CLK_MAX_WIRE_LENGTH",
    "CTS_DISABLE_POST_PROCESSING",
    "CTS_DISTANCE_BETWEEN_BUFFERS",
    "CTS_CORNERS",
    "CTS_ROOT_BUFFER",
    "CTS_CLK_BUFFERS",
    "CTS_MAX_CAP",
    "CTS_MAX_SLEW",
]

# IOPlacement config keys (io_layer_variables + IOPlacement-specific)
IO_PLACEMENT_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "FP_IO_VEXTEND",
    "FP_IO_HEXTEND",
    "FP_IO_VTHICKNESS_MULT",
    "FP_IO_HTHICKNESS_MULT",
    "FP_PPL_MODE",
    "FP_IO_MIN_DISTANCE",
    "FP_PIN_ORDER_CFG",
    "FP_IO_VLENGTH",
    "FP_IO_HLENGTH",
    "FP_DEF_TEMPLATE",
]

# CustomIOPlacement config keys (io_layer_variables + CustomIOPlacement-specific)
CUSTOM_IO_PLACEMENT_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "FP_IO_VEXTEND",
    "FP_IO_HEXTEND",
    "FP_IO_VTHICKNESS_MULT",
    "FP_IO_HTHICKNESS_MULT",
    "FP_IO_VLENGTH",
    "FP_IO_HLENGTH",
    "FP_PIN_ORDER_CFG",
    "ERRORS_ON_UNMATCHED_IO",
]

# ApplyDEFTemplate config keys (odb.py lines 243-259)
APPLY_DEF_TEMPLATE_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "FP_DEF_TEMPLATE",
    "FP_TEMPLATE_MATCH_MODE",
    "FP_TEMPLATE_COPY_POWER_PINS",
]

# OpenROAD.CutRows and OpenROAD.TapEndcapInsertion config keys
CUTROWS_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "FP_MACRO_HORIZONTAL_HALO",
    "FP_MACRO_VERTICAL_HALO",
]

# _GlobalPlacement base config keys (routing_layer_variables + placement vars)
_GPL_BASE_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "PL_TARGET_DENSITY_PCT",
    "PL_SKIP_INITIAL_PLACEMENT",
    "PL_WIRE_LENGTH_COEF",
    "PL_MIN_PHI_COEFFICIENT",
    "PL_MAX_PHI_COEFFICIENT",
    "FP_CORE_UTIL",
    "GPL_CELL_PADDING",
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
]

# GlobalPlacementSkipIO config keys (_GlobalPlacement + FP_PPL_MODE)
GPL_SKIP_IO_CONFIG_KEYS = _GPL_BASE_CONFIG_KEYS + [
    "FP_PPL_MODE",
]

# GlobalPlacement config keys (_GlobalPlacement + time/routability vars)
GPL_CONFIG_KEYS = _GPL_BASE_CONFIG_KEYS + [
    "PL_TIME_DRIVEN",
    "PL_ROUTABILITY_DRIVEN",
    "PL_ROUTABILITY_OVERFLOW_THRESHOLD",
]

# OpenROAD.GeneratePDN config keys (pdn_variables from common_variables.py)
PDN_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # User-configurable
    "FP_PDN_SKIPTRIM",
    "FP_PDN_CORE_RING",
    "FP_PDN_ENABLE_RAILS",
    "FP_PDN_HORIZONTAL_HALO",
    "FP_PDN_VERTICAL_HALO",
    "FP_PDN_MULTILAYER",
    "FP_PDN_CFG",
    # PDK-level (from pdk provider)
    "FP_PDN_RAIL_LAYER",
    "FP_PDN_RAIL_WIDTH",
    "FP_PDN_RAIL_OFFSET",
    "FP_PDN_HORIZONTAL_LAYER",
    "FP_PDN_VERTICAL_LAYER",
    "FP_PDN_HOFFSET",
    "FP_PDN_VOFFSET",
    "FP_PDN_HPITCH",
    "FP_PDN_VPITCH",
    "FP_PDN_HSPACING",
    "FP_PDN_VSPACING",
    "FP_PDN_HWIDTH",
    "FP_PDN_VWIDTH",
    "FP_PDN_CORE_RING_HOFFSET",
    "FP_PDN_CORE_RING_VOFFSET",
    "FP_PDN_CORE_RING_HSPACING",
    "FP_PDN_CORE_RING_VSPACING",
    "FP_PDN_CORE_RING_HWIDTH",
    "FP_PDN_CORE_RING_VWIDTH",
]

def _macro_placement_impl(ctx):
    extra = {
        "PL_MACRO_HALO": ctx.attr.macro_halo,
        "PL_MACRO_CHANNEL": ctx.attr.macro_channel,
    }
    return single_step_impl(ctx, "OpenROAD.BasicMacroPlacement", PLACE_CONFIG_KEYS,
        step_outputs = ["def", "odb"], extra_config = extra)

def _manual_macro_placement_impl(ctx):
    extra = {
        "MACRO_PLACEMENT_CFG": ctx.file.macro_placement_cfg.path,
    }
    extra_inputs = [ctx.file.macro_placement_cfg]
    return single_step_impl(ctx, "Odb.ManualMacroPlacement", PLACE_CONFIG_KEYS,
        step_outputs = ["def", "odb"], extra_config = extra, extra_inputs = extra_inputs)

def _cut_rows_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.CutRows", CUTROWS_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _tap_endcap_insertion_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.TapEndcapInsertion", CUTROWS_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _generate_pdn_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.GeneratePDN", PDN_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _global_placement_skip_io_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.GlobalPlacementSkipIO", GPL_SKIP_IO_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _io_placement_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.IOPlacement", IO_PLACEMENT_CONFIG_KEYS,
        step_outputs = ["def", "odb"])

def _custom_io_placement_impl(ctx):
    return single_step_impl(ctx, "Odb.CustomIOPlacement", CUSTOM_IO_PLACEMENT_CONFIG_KEYS,
        step_outputs = ["def", "odb"])

def _apply_def_template_impl(ctx):
    return single_step_impl(ctx, "Odb.ApplyDEFTemplate", APPLY_DEF_TEMPLATE_CONFIG_KEYS,
        step_outputs = ["def", "odb"])

def _global_placement_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.GlobalPlacement", GPL_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _repair_design_post_gpl_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.RepairDesignPostGPL", REPAIR_DESIGN_CONFIG_KEYS,
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _detailed_placement_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.DetailedPlacement", DPL_CONFIG_KEYS, step_outputs = ["def", "odb"])

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
    inputs = get_input_files(input_info, state_info)

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

_manual_macro_placement_attrs = dict(FLOW_ATTRS, **{
    "macro_placement_cfg": attr.label(
        doc = "Macro placement configuration file (instance X Y orientation)",
        allow_single_file = True,
        mandatory = True,
    ),
})

librelane_macro_placement = rule(
    implementation = _macro_placement_impl,
    attrs = _macro_placement_attrs,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_manual_macro_placement = rule(
    implementation = _manual_macro_placement_impl,
    attrs = _manual_macro_placement_attrs,
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
