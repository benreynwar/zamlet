# Placement rules

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "single_step_impl",
    "FLOW_ATTRS",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
)

def _macro_placement_impl(ctx):
    extra = {
        "PL_MACRO_HALO": ctx.attr.macro_halo,
        "PL_MACRO_CHANNEL": ctx.attr.macro_channel,
    }
    return single_step_impl(ctx, "OpenROAD.BasicMacroPlacement",
        step_outputs = ["def", "odb"], extra_config = extra)

def _manual_macro_placement_impl(ctx):
    extra = {
        "MACRO_PLACEMENT_CFG": ctx.file.macro_placement_cfg.path,
    }
    extra_inputs = [ctx.file.macro_placement_cfg]
    return single_step_impl(ctx, "Odb.ManualMacroPlacement",
        step_outputs = ["def", "odb"], extra_config = extra, extra_inputs = extra_inputs)

def _cut_rows_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.CutRows", step_outputs = ["def", "odb"])

def _tap_endcap_insertion_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.TapEndcapInsertion",
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _generate_pdn_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.GeneratePDN",
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _global_placement_skip_io_impl(ctx):
    extra = {}
    if ctx.attr.target_density:
        extra["PL_TARGET_DENSITY_PCT"] = int(float(ctx.attr.target_density) * 100)
    return single_step_impl(ctx, "OpenROAD.GlobalPlacementSkipIO",
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"], extra_config = extra)

def _io_placement_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.IOPlacement", step_outputs = ["def", "odb"])

def _custom_io_placement_impl(ctx):
    extra = {
        "FP_PIN_ORDER_CFG": ctx.file.pin_order_cfg.path,
    }
    extra_inputs = [ctx.file.pin_order_cfg]
    return single_step_impl(ctx, "Odb.CustomIOPlacement",
        step_outputs = ["def", "odb"], extra_config = extra, extra_inputs = extra_inputs)

def _apply_def_template_impl(ctx):
    extra = {
        "FP_DEF_TEMPLATE": ctx.file.def_template.path,
        "FP_TEMPLATE_MATCH_MODE": ctx.attr.match_mode,
    }
    extra_inputs = [ctx.file.def_template]
    return single_step_impl(ctx, "Odb.ApplyDEFTemplate",
        step_outputs = ["def", "odb"], extra_config = extra, extra_inputs = extra_inputs)

def _global_placement_impl(ctx):
    extra = {}
    if ctx.attr.target_density:
        extra["PL_TARGET_DENSITY_PCT"] = int(float(ctx.attr.target_density) * 100)
    return single_step_impl(ctx, "OpenROAD.GlobalPlacement",
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"], extra_config = extra)

def _repair_design_post_gpl_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.RepairDesignPostGPL",
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _detailed_placement_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.DetailedPlacement", step_outputs = ["def", "odb"])

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

    # Create config with CTS options
    config = create_librelane_config(input_info, state_info)
    if ctx.attr.cts_clk_max_wire_length:
        config["CTS_CLK_MAX_WIRE_LENGTH"] = float(ctx.attr.cts_clk_max_wire_length)

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
    return single_step_impl(ctx, "OpenROAD.ResizerTimingPostCTS",
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

_gpl_attrs = dict(FLOW_ATTRS, **{
    "target_density": attr.string(doc = "Target placement density (0.0-1.0)"),
})

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
    attrs = _gpl_attrs,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_io_placement = rule(
    implementation = _io_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

_custom_io_attrs = dict(FLOW_ATTRS, **{
    "pin_order_cfg": attr.label(
        doc = "Pin order configuration file for custom IO placement",
        allow_single_file = True,
        mandatory = True,
    ),
})

librelane_custom_io_placement = rule(
    implementation = _custom_io_placement_impl,
    attrs = _custom_io_attrs,
    provides = [DefaultInfo, LibrelaneInfo],
)

_apply_def_template_attrs = dict(FLOW_ATTRS, **{
    "def_template": attr.label(
        doc = "DEF template file with die area and pin placements",
        allow_single_file = [".def"],
        mandatory = True,
    ),
    "match_mode": attr.string(
        doc = "Pin matching mode: 'strict' requires identical pins, 'permissive' allows mismatches",
        default = "strict",
        values = ["strict", "permissive"],
    ),
})

librelane_apply_def_template = rule(
    implementation = _apply_def_template_impl,
    attrs = _apply_def_template_attrs,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_global_placement = rule(
    implementation = _global_placement_impl,
    attrs = _gpl_attrs,
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

_cts_attrs = dict(FLOW_ATTRS, **{
    "cts_clk_max_wire_length": attr.string(
        doc = "Maximum wire length on clock net in µm. Buffers inserted for longer wires. " +
              "Default 0 disables. Recommended: 100-800 for large designs.",
    ),
})

librelane_cts = rule(
    implementation = _cts_impl,
    attrs = _cts_attrs,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_resizer_timing_post_cts = rule(
    implementation = _resizer_timing_post_cts_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
