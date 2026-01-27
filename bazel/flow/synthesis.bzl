# Synthesis rule - produces netlist from RTL

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
    "FLOW_ATTRS",
)

def _synthesis_impl(ctx):
    """Synthesize verilog to gate-level netlist."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # Declare outputs in target directory (librelane writes elsewhere, we copy)
    # Note: Yosys.Synthesis only outputs netlist, not SDC
    nl = ctx.actions.declare_file(ctx.label.name + "/" + top + ".nl.v")
    stat_json = ctx.actions.declare_file(ctx.label.name + "/reports/stat.json")

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config
    config = create_librelane_config(input_info, state_info)

    # Run synthesis
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "Yosys.Synthesis",
        outputs = [nl, stat_json],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset([nl, stat_json])),
        LibrelaneInfo(
            state_out = state_out,
            nl = nl,
            pnl = None,
            odb = None,
            sdc = None,
            sdf = None,
            spef = None,
            lib = None,
            gds = None,
            mag_gds = None,
            klayout_gds = None,
            lef = None,
            mag = None,
            spice = None,
            json_h = state_info.json_h,
            vh = None,
            **{"def": None}
        ),
    ]

librelane_synthesis = rule(
    implementation = _synthesis_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

def _json_header_impl(ctx):
    """Generate JSON header with power connection info."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # Declare output
    json_h = ctx.actions.declare_file(ctx.label.name + "/" + top + ".h.json")

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config
    config = create_librelane_config(input_info, state_info)

    # Run step
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "Yosys.JsonHeader",
        outputs = [json_h],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset([json_h])),
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
            json_h = json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

librelane_json_header = rule(
    implementation = _json_header_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

def _eqy_impl(ctx):
    """Formal equivalence check: RTL vs gate-level netlist."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]

    # Get input files
    inputs = get_input_files(input_info, state_info)

    # Create config
    config = create_librelane_config(input_info, state_info)

    # Run step
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "Yosys.EQY",
        outputs = [],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
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

librelane_eqy = rule(
    implementation = _eqy_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
