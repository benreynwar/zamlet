# Static Timing Analysis rules

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "single_step_impl",
    "FLOW_ATTRS",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
)

def _check_sdc_files_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.CheckSDCFiles", step_outputs = [])

def _check_macro_instances_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.CheckMacroInstances", step_outputs = [])

def _sta_pre_pnr_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.STAPrePNR", step_outputs = [])

def _sta_mid_pnr_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.STAMidPNR", step_outputs = [])

def _rcx_impl(ctx):
    """Parasitic extraction - produces SPEF for all corners (passes through def/odb)."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # RCX produces SPEF for each corner (nom, min, max)
    spef_nom = ctx.actions.declare_file(ctx.label.name + "/nom/" + top + ".nom.spef")
    spef_min = ctx.actions.declare_file(ctx.label.name + "/min/" + top + ".min.spef")
    spef_max = ctx.actions.declare_file(ctx.label.name + "/max/" + top + ".max.spef")

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config
    config = create_librelane_config(input_info, state_info)

    # Run RCX
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.RCX",
        outputs = [spef_nom, spef_min, spef_max],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset([spef_nom, spef_min, spef_max])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = state_info.sdf,
            spef = {"nom_*": spef_nom, "min_*": spef_min, "max_*": spef_max},
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

def _sta_post_pnr_impl(ctx):
    """Post-PnR timing analysis with timing reports."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # Get STA corners from PDK
    sta_corners = input_info.pdk_info.sta_corners

    # Declare report outputs for each corner (both setup/max and hold/min)
    report_outputs = []
    for corner in sta_corners:
        report_outputs.append(ctx.actions.declare_file(
            ctx.label.name + "/" + corner + "/max.rpt"))
        report_outputs.append(ctx.actions.declare_file(
            ctx.label.name + "/" + corner + "/min.rpt"))

    # Also declare summary report
    summary_report = ctx.actions.declare_file(ctx.label.name + "/summary.rpt")

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config
    config = create_librelane_config(input_info, state_info)

    # Run STA with report outputs
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.STAPostPNR",
        outputs = report_outputs + [summary_report],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset(report_outputs + [summary_report, state_out])),
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

def _ir_drop_report_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.IRDropReport", step_outputs = [])

librelane_check_sdc_files = rule(
    implementation = _check_sdc_files_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_check_macro_instances = rule(
    implementation = _check_macro_instances_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_sta_pre_pnr = rule(
    implementation = _sta_pre_pnr_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_sta_mid_pnr = rule(
    implementation = _sta_mid_pnr_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_rcx = rule(
    implementation = _rcx_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_sta_post_pnr = rule(
    implementation = _sta_post_pnr_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_ir_drop_report = rule(
    implementation = _ir_drop_report_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
