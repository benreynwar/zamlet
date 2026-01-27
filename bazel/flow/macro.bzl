# Hard macro generation rules (Fill, GDS, LEF) and Magic steps

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo", "MacroInfo")
load(":common.bzl",
    "create_librelane_config",
    "run_librelane_step",
    "single_step_impl",
    "get_input_files",
    "FLOW_ATTRS",
)

def _fill_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.FillInsertion",
        step_outputs = ["def", "odb", "nl", "pnl", "sdc"])

def _gds_impl(ctx):
    """Generate GDSII layout."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # Declare GDS output in target directory
    gds = ctx.actions.declare_file(ctx.label.name + "/" + top + ".gds")

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config
    config = create_librelane_config(input_info, state_info)

    # Run GDS generation
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "Magic.StreamOut",
        outputs = [gds],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset([gds])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = state_info.sdf,
            spef = state_info.spef,
            lib = state_info.lib,
            gds = gds,
            mag_gds = gds,  # Magic.StreamOut produces the MAG_GDS
            klayout_gds = state_info.klayout_gds,
            lef = state_info.lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

def _lef_impl(ctx):
    """Generate LEF abstract and provide MacroInfo for hierarchical use."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # Declare LEF output in target directory
    lef = ctx.actions.declare_file(ctx.label.name + "/" + top + ".lef")

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config
    config = create_librelane_config(input_info, state_info)

    # Run LEF generation
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "Magic.WriteLEF",
        outputs = [lef],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    # Create MacroInfo for hierarchical designs
    macro_info = MacroInfo(
        name = top,
        lef = lef,
        gds = state_info.gds,
        netlist = state_info.nl,
    )

    return [
        DefaultInfo(files = depset([lef])),
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
            lef = lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
        macro_info,
    ]

def _drc_impl(ctx):
    return single_step_impl(ctx, "Magic.DRC", step_outputs = [])

def _spice_extraction_impl(ctx):
    return single_step_impl(ctx, "Magic.SpiceExtraction", step_outputs = ["spice"])

librelane_fill = rule(
    implementation = _fill_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_gds = rule(
    implementation = _gds_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_lef = rule(
    implementation = _lef_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo, MacroInfo],
)

librelane_magic_drc = rule(
    implementation = _drc_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_spice_extraction = rule(
    implementation = _spice_extraction_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
