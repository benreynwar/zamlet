# Synthesis rule - produces netlist from RTL

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load(":common.bzl",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
    "FLOW_ATTRS",
    "BASE_CONFIG_KEYS",
)

# Config keys for Yosys.JsonHeader (from librelane/steps/pyosys.py)
# Inherits: JsonHeader -> VerilogStep -> PyosysStep -> Step
# config_vars = PyosysStep.config_vars + verilog_rtl_cfg_vars
JSON_HEADER_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # verilog_rtl_cfg_vars (pyosys.py lines 95-136)
    "VERILOG_FILES",
    "VERILOG_DEFINES",
    "VERILOG_POWER_DEFINE",
    "VERILOG_INCLUDE_DIRS",
    "SYNTH_PARAMETERS",
    "USE_SYNLIG",
    "SYNLIG_DEFER",
    # PyosysStep.config_vars (pyosys.py lines 140-204)
    "SYNTH_LATCH_MAP",
    "SYNTH_TRISTATE_MAP",
    "SYNTH_CSA_MAP",
    "SYNTH_RCA_MAP",
    "SYNTH_FA_MAP",
    "SYNTH_MUX_MAP",
    "SYNTH_MUX4_MAP",
    "USE_LIGHTER",
    "LIGHTER_DFF_MAP",
    "YOSYS_LOG_LEVEL",
]

# Config keys for Yosys.Synthesis (from librelane/steps/pyosys.py)
# Inherits: Synthesis -> SynthesisCommon -> VerilogStep -> PyosysStep -> Step
# config_vars = SynthesisCommon.config_vars + verilog_rtl_cfg_vars
SYNTHESIS_CONFIG_KEYS = JSON_HEADER_CONFIG_KEYS + [
    # SynthesisCommon.config_vars (pyosys.py lines 346-496)
    "TRISTATE_CELLS",  # PDK config, used in run() for check parsing
    "SYNTH_CHECKS_ALLOW_TRISTATE",
    "SYNTH_AUTONAME",
    "SYNTH_STRATEGY",
    "SYNTH_ABC_BUFFERING",
    "SYNTH_ABC_LEGACY_REFACTOR",
    "SYNTH_ABC_LEGACY_REWRITE",
    "SYNTH_ABC_DFF",
    "SYNTH_ABC_USE_MFS3",
    "SYNTH_ABC_AREA_USE_NF",
    "SYNTH_DIRECT_WIRE_BUFFERING",
    "SYNTH_SPLITNETS",
    "SYNTH_SIZING",
    "SYNTH_HIERARCHY_MODE",
    "SYNTH_SHARE_RESOURCES",
    "SYNTH_ADDER_TYPE",
    "SYNTH_EXTRA_MAPPING_FILE",
    "SYNTH_ELABORATE_ONLY",
    "SYNTH_ELABORATE_FLATTEN",
    "SYNTH_MUL_BOOTH",
    "SYNTH_TIE_UNDEFINED",
    "SYNTH_WRITE_NOATTR",
]

# Step 73: Yosys.EQY - yosys.py lines 250-350
# Inherits YosysStep.config_vars + verilog_rtl_cfg_vars (most in SYNTHESIS_CONFIG_KEYS)
# EQY-specific config from lines 266-287
EQY_CONFIG_KEYS = SYNTHESIS_CONFIG_KEYS + [
    "RUN_EQY",
    "EQY_SCRIPT",
    "EQY_FORCE_ACCEPT_PDK",
    "MACRO_PLACEMENT_CFG",
]

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
    config = create_librelane_config(input_info, state_info, SYNTHESIS_CONFIG_KEYS)

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
    config = create_librelane_config(input_info, state_info, JSON_HEADER_CONFIG_KEYS)

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
    config = create_librelane_config(input_info, state_info, EQY_CONFIG_KEYS)

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
