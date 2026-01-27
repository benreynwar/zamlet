# Floorplan rule - creates initial placement area

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
    "FLOW_ATTRS",
)

def _floorplan_impl(ctx):
    """Create floorplan with die area and pin placement.

    OpenROAD.Floorplan produces all standard outputs: def, odb, nl, pnl, sdc.
    """
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # Declare all OpenROAD outputs
    def_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".def")
    odb_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".odb")
    nl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".nl.v")
    pnl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".pnl.v")
    sdc_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".sdc")

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config with floorplan settings
    config = create_librelane_config(input_info, state_info)
    if ctx.attr.die_area:
        config["FP_SIZING"] = "absolute"
        config["DIE_AREA"] = [float(x) for x in ctx.attr.die_area.split(" ")]
    if ctx.attr.core_area:
        config["CORE_AREA"] = [float(x) for x in ctx.attr.core_area.split(" ")]
    if ctx.attr.core_utilization and not ctx.attr.die_area:
        config["FP_CORE_UTIL"] = int(ctx.attr.core_utilization)

    # Run floorplan with all outputs
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.Floorplan",
        outputs = [def_out, odb_out, nl_out, pnl_out, sdc_out],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset([def_out, odb_out, nl_out, pnl_out, sdc_out])),
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

librelane_floorplan = rule(
    implementation = _floorplan_impl,
    attrs = dict(FLOW_ATTRS, **{
        "die_area": attr.string(doc = "Die area as 'x0 y0 x1 y1' in microns"),
        "core_area": attr.string(doc = "Core area as 'x0 y0 x1 y1' in microns"),
        "core_utilization": attr.string(
            doc = "Target core utilization percentage (0-100)",
            default = "40",
        ),
    }),
    provides = [DefaultInfo, LibrelaneInfo],
)
