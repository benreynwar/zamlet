# Floorplan rule - creates initial placement area

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
    "FLOW_ATTRS",
    "BASE_CONFIG_KEYS",
)

# Config keys needed by floorplan step (from floorplan.tcl and common/io.tcl)
FLOORPLAN_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # Floorplan-specific keys (set in impl, not from create_librelane_config)
    "FP_SIZING", "DIE_AREA", "CORE_AREA", "FP_CORE_UTIL", "FP_ASPECT_RATIO",
    "BOTTOM_MARGIN_MULT", "TOP_MARGIN_MULT", "LEFT_MARGIN_MULT", "RIGHT_MARGIN_MULT",
    "FP_OBSTRUCTIONS", "PL_SOFT_OBSTRUCTIONS",
]

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
    config = create_librelane_config(input_info, state_info, FLOORPLAN_CONFIG_KEYS)

    # Margin multipliers (always set, have defaults matching librelane)
    config["BOTTOM_MARGIN_MULT"] = int(ctx.attr.bottom_margin_mult)
    config["TOP_MARGIN_MULT"] = int(ctx.attr.top_margin_mult)
    config["LEFT_MARGIN_MULT"] = int(ctx.attr.left_margin_mult)
    config["RIGHT_MARGIN_MULT"] = int(ctx.attr.right_margin_mult)

    if ctx.attr.die_area:
        # Absolute sizing mode
        config["FP_SIZING"] = "absolute"
        config["DIE_AREA"] = [float(x) for x in ctx.attr.die_area.split(" ")]
        if ctx.attr.core_area:
            config["CORE_AREA"] = [float(x) for x in ctx.attr.core_area.split(" ")]
    else:
        # Relative sizing mode (default)
        config["FP_SIZING"] = "relative"
        config["FP_CORE_UTIL"] = int(ctx.attr.core_utilization)
        config["FP_ASPECT_RATIO"] = float(ctx.attr.fp_aspect_ratio)

    # Optional obstructions
    if ctx.attr.fp_obstructions:
        config["FP_OBSTRUCTIONS"] = [
            [float(x) for x in obs.split(" ")] for obs in ctx.attr.fp_obstructions
        ]
    if ctx.attr.pl_soft_obstructions:
        config["PL_SOFT_OBSTRUCTIONS"] = [
            [float(x) for x in obs.split(" ")] for obs in ctx.attr.pl_soft_obstructions
        ]

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
            default = "50",
        ),
        "fp_aspect_ratio": attr.string(
            doc = "Core aspect ratio (height / width)",
            default = "1",
        ),
        "bottom_margin_mult": attr.string(
            doc = "Core margin from bottom in multiples of site height",
            default = "4",
        ),
        "top_margin_mult": attr.string(
            doc = "Core margin from top in multiples of site height",
            default = "4",
        ),
        "left_margin_mult": attr.string(
            doc = "Core margin from left in multiples of site width",
            default = "12",
        ),
        "right_margin_mult": attr.string(
            doc = "Core margin from right in multiples of site width",
            default = "12",
        ),
        "fp_obstructions": attr.string_list(
            doc = "Floorplan obstructions as 'x0 y0 x1 y1' strings in microns",
            default = [],
        ),
        "pl_soft_obstructions": attr.string_list(
            doc = "Soft placement obstructions as 'x0 y0 x1 y1' strings in microns",
            default = [],
        ),
    }),
    provides = [DefaultInfo, LibrelaneInfo],
)
