# Init rule - entry point for the flow

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo", "PdkInfo", "MacroInfo")
load(":common.bzl", "ENTRY_ATTRS")

def _init_impl(ctx):
    """Package verilog files and config into LibrelaneInput and LibrelaneInfo."""
    pdk_info = ctx.attr.pdk[PdkInfo]

    # Collect macros if provided
    macros = []
    if ctx.attr.macros:
        for macro_target in ctx.attr.macros:
            macros.append(macro_target[MacroInfo])

    # Get optional SDC files
    pnr_sdc = ctx.file.pnr_sdc_file if ctx.attr.pnr_sdc_file else None
    signoff_sdc = ctx.file.signoff_sdc_file if ctx.attr.signoff_sdc_file else None

    return [
        DefaultInfo(files = depset(ctx.files.verilog_files)),
        # LibrelaneInput - configuration that doesn't change
        LibrelaneInput(
            top = ctx.attr.top,
            clock_port = ctx.attr.clock_port,
            clock_period = ctx.attr.clock_period,
            pdk_info = pdk_info,
            verilog_files = depset(ctx.files.verilog_files),
            macros = macros,
            pnr_sdc_file = pnr_sdc,
            signoff_sdc_file = signoff_sdc,
        ),
        # LibrelaneInfo - initial state (all empty)
        LibrelaneInfo(
            state_out = None,
            nl = None,
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
            json_h = None,
            vh = None,
            **{"def": None}
        ),
    ]

librelane_init = rule(
    implementation = _init_impl,
    attrs = ENTRY_ATTRS,
    provides = [DefaultInfo, LibrelaneInput, LibrelaneInfo],
)
