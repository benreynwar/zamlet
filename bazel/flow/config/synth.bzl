# Synthesis configuration attributes and rule
#
# These ~35 attributes control linting, Yosys synthesis, and EQY.

SynthConfig = provider(
    doc = "Synthesis configuration.",
    fields = {
        # Linter config
        "verilog_power_define": "Power guard define name",
        "linter_include_pdk_models": "Include PDK Verilog models in linting",
        "linter_relative_includes": "Resolve includes relative to file",
        "linter_error_on_latch": "Error on inferred latches",
        "linter_defines": "Linter-specific preprocessor defines (list)",
        "extra_verilog_models": "Extra Verilog models (list of Files)",

        # Yosys config
        "synth_parameters": "Key-value pairs for Yosys chparam (list)",
        "use_synlig": "Use Synlig plugin for SystemVerilog",
        "synlig_defer": "Use -defer flag with Synlig",
        "use_lighter": "Use Lighter plugin for clock-gated FFs",
        "lighter_dff_map": "File - Custom DFF map for Lighter",
        "yosys_log_level": "Yosys log level (ALL, WARNING, ERROR)",

        # Yosys.Synthesis config
        "synth_checks_allow_tristate": "Ignore multi-driver warnings for tristate",
        "synth_autoname": "Generate human-readable instance names",
        "synth_strategy": "ABC synthesis strategy",
        "synth_abc_buffering": "Enable ABC cell buffering",
        "synth_abc_legacy_refactor": "Use legacy ABC refactor",
        "synth_abc_legacy_rewrite": "Use legacy ABC rewrite",
        "synth_abc_dff": "Pass DFFs through ABC",
        "synth_abc_use_mfs3": "Experimental SAT-based remapping",
        "synth_abc_area_use_nf": "Experimental &nf area mapper",
        "synth_direct_wire_buffering": "Buffer directly connected wires",
        "synth_splitnets": "Split multi-bit nets",
        "synth_sizing": "Enable ABC cell sizing",
        "synth_hierarchy_mode": "Hierarchy handling mode",
        "synth_share_resources": "Merge shareable resources",
        "synth_adder_type": "Adder mapping type",
        "synth_extra_mapping_file": "File - Extra techmap file",
        "synth_elaborate_only": "Elaborate without logic mapping",
        "synth_elaborate_flatten": "Flatten during elaborate-only",
        "synth_mul_booth": "Use Booth encoding for multipliers",
        "synth_tie_undefined": "Tie undefined values (high/low/empty)",
        "synth_write_noattr": "Omit Verilog attributes from netlist",

        # EQY config
        "run_eqy": "Enable EQY formal equivalence check",
        "eqy_script": "File - Custom EQY script",
        "eqy_force_accept_pdk": "Force EQY on unsupported PDK",
    },
)

SYNTH_ATTRS = {
    # Verilator.Lint config (from librelane/steps/verilator.py lines 39-87)
    "verilog_power_define": attr.string(
        doc = "Power guard define name for Verilog preprocessing",
        default = "USE_POWER_PINS",
    ),
    "linter_include_pdk_models": attr.bool(
        doc = "Include PDK Verilog models in linting",
        default = False,
    ),
    "linter_relative_includes": attr.bool(
        doc = "Resolve includes relative to referencing file",
        default = True,
    ),
    "linter_error_on_latch": attr.bool(
        doc = "Error on inferred latches not marked always_latch",
        default = True,
    ),
    "linter_defines": attr.string_list(
        doc = "Linter-specific preprocessor defines (overrides verilog_defines for lint)",
        default = [],
    ),
    "extra_verilog_models": attr.label_list(
        doc = "Extra Verilog models for linting and synthesis",
        allow_files = [".v", ".sv"],
        default = [],
    ),
    # Yosys config (from librelane/steps/pyosys.py verilog_rtl_cfg_vars + PyosysStep.config_vars)
    "synth_parameters": attr.string_list(
        doc = "Key-value pairs to be chparam'd in Yosys (format: key1=value1)",
        default = [],
    ),
    "use_synlig": attr.bool(
        doc = "Use Synlig plugin for better SystemVerilog parsing",
        default = False,
    ),
    "synlig_defer": attr.bool(
        doc = "Use -defer flag with Synlig (experimental)",
        default = False,
    ),
    "use_lighter": attr.bool(
        doc = "Use Lighter plugin to optimize clock-gated flip-flops",
        default = False,
    ),
    "lighter_dff_map": attr.label(
        doc = "Custom DFF map file for Lighter plugin",
        allow_single_file = True,
    ),
    "yosys_log_level": attr.string(
        doc = "Yosys log level: ALL, WARNING, or ERROR",
        default = "ALL",
        values = ["ALL", "WARNING", "ERROR"],
    ),
    # Yosys.Synthesis config (from librelane/steps/pyosys.py SynthesisCommon.config_vars)
    "synth_checks_allow_tristate": attr.bool(
        doc = "Ignore multiple-driver warnings for tri-state buffers",
        default = True,
    ),
    "synth_autoname": attr.bool(
        doc = "Generate human-readable names for netlist instances",
        default = False,
    ),
    "synth_strategy": attr.string(
        doc = "ABC synthesis strategy: AREA 0-3 or DELAY 0-4",
        default = "AREA 0",
        values = ["AREA 0", "AREA 1", "AREA 2", "AREA 3",
                  "DELAY 0", "DELAY 1", "DELAY 2", "DELAY 3", "DELAY 4"],
    ),
    "synth_abc_buffering": attr.bool(
        doc = "Enable ABC cell buffering",
        default = False,
    ),
    "synth_abc_legacy_refactor": attr.bool(
        doc = "Use legacy ABC refactor command (less stable)",
        default = False,
    ),
    "synth_abc_legacy_rewrite": attr.bool(
        doc = "Use legacy ABC rewrite command (less stable)",
        default = False,
    ),
    "synth_abc_dff": attr.bool(
        doc = "Pass D-flipflops through ABC for optimization",
        default = False,
    ),
    "synth_abc_use_mfs3": attr.bool(
        doc = "Experimental: SAT-based remapping before retime",
        default = False,
    ),
    "synth_abc_area_use_nf": attr.bool(
        doc = "Experimental: use &nf mapper instead of amap for area",
        default = False,
    ),
    "synth_direct_wire_buffering": attr.bool(
        doc = "Insert buffer cells for directly connected wires",
        default = True,
    ),
    "synth_splitnets": attr.bool(
        doc = "Split multi-bit nets into single-bit nets",
        default = True,
    ),
    "synth_sizing": attr.bool(
        doc = "Enable ABC cell sizing instead of buffering",
        default = False,
    ),
    "synth_hierarchy_mode": attr.string(
        doc = "Hierarchy handling: flatten, deferred_flatten, or keep",
        default = "flatten",
        values = ["flatten", "deferred_flatten", "keep"],
    ),
    "synth_share_resources": attr.bool(
        doc = "Merge shareable resources to reduce cell count",
        default = True,
    ),
    "synth_adder_type": attr.string(
        doc = "Adder mapping: YOSYS, FA, RCA, or CSA",
        default = "YOSYS",
        values = ["YOSYS", "FA", "RCA", "CSA"],
    ),
    "synth_extra_mapping_file": attr.label(
        doc = "Extra techmap file for Yosys",
        allow_single_file = True,
    ),
    "synth_elaborate_only": attr.bool(
        doc = "Elaborate design without logic mapping",
        default = False,
    ),
    "synth_elaborate_flatten": attr.bool(
        doc = "Flatten top level during elaborate-only mode",
        default = True,
    ),
    "synth_mul_booth": attr.bool(
        doc = "Use Booth encoding for multipliers",
        default = False,
    ),
    "synth_tie_undefined": attr.string(
        doc = "Tie undefined values: high, low, or empty for undriven",
        default = "low",
        values = ["high", "low", ""],
    ),
    "synth_write_noattr": attr.bool(
        doc = "Omit Verilog-2001 attributes from output netlists",
        default = True,
    ),
    # Yosys.EQY gating (classic.py:253-256) - NOTE: defaults to False
    "run_eqy": attr.bool(
        doc = "Enable Yosys EQY formal equivalence check (disabled by default)",
        default = False,
    ),
    # Yosys.EQY config (yosys.py:266-287)
    "eqy_script": attr.label(
        doc = "Custom EQY script file",
        allow_single_file = True,
    ),
    "eqy_force_accept_pdk": attr.bool(
        doc = "Force EQY to run even if PDK not officially supported",
        default = False,
    ),
}

# Default values for synthesis config
SYNTH_DEFAULTS = {
    "verilog_power_define": "USE_POWER_PINS",
    "linter_include_pdk_models": False,
    "linter_relative_includes": True,
    "linter_error_on_latch": True,
    "linter_defines": [],
    "extra_verilog_models": [],
    "synth_parameters": [],
    "use_synlig": False,
    "synlig_defer": False,
    "use_lighter": False,
    "lighter_dff_map": None,
    "yosys_log_level": "ALL",
    "synth_checks_allow_tristate": True,
    "synth_autoname": False,
    "synth_strategy": "AREA 0",
    "synth_abc_buffering": False,
    "synth_abc_legacy_refactor": False,
    "synth_abc_legacy_rewrite": False,
    "synth_abc_dff": False,
    "synth_abc_use_mfs3": False,
    "synth_abc_area_use_nf": False,
    "synth_direct_wire_buffering": True,
    "synth_splitnets": True,
    "synth_sizing": False,
    "synth_hierarchy_mode": "flatten",
    "synth_share_resources": True,
    "synth_adder_type": "YOSYS",
    "synth_extra_mapping_file": None,
    "synth_elaborate_only": False,
    "synth_elaborate_flatten": True,
    "synth_mul_booth": False,
    "synth_tie_undefined": "low",
    "synth_write_noattr": True,
    "run_eqy": False,
    "eqy_script": None,
    "eqy_force_accept_pdk": False,
}


def _synth_config_impl(ctx):
    return [SynthConfig(
        verilog_power_define = ctx.attr.verilog_power_define,
        linter_include_pdk_models = ctx.attr.linter_include_pdk_models,
        linter_relative_includes = ctx.attr.linter_relative_includes,
        linter_error_on_latch = ctx.attr.linter_error_on_latch,
        linter_defines = ctx.attr.linter_defines,
        extra_verilog_models = ctx.files.extra_verilog_models,
        synth_parameters = ctx.attr.synth_parameters,
        use_synlig = ctx.attr.use_synlig,
        synlig_defer = ctx.attr.synlig_defer,
        use_lighter = ctx.attr.use_lighter,
        lighter_dff_map = ctx.file.lighter_dff_map,
        yosys_log_level = ctx.attr.yosys_log_level,
        synth_checks_allow_tristate = ctx.attr.synth_checks_allow_tristate,
        synth_autoname = ctx.attr.synth_autoname,
        synth_strategy = ctx.attr.synth_strategy,
        synth_abc_buffering = ctx.attr.synth_abc_buffering,
        synth_abc_legacy_refactor = ctx.attr.synth_abc_legacy_refactor,
        synth_abc_legacy_rewrite = ctx.attr.synth_abc_legacy_rewrite,
        synth_abc_dff = ctx.attr.synth_abc_dff,
        synth_abc_use_mfs3 = ctx.attr.synth_abc_use_mfs3,
        synth_abc_area_use_nf = ctx.attr.synth_abc_area_use_nf,
        synth_direct_wire_buffering = ctx.attr.synth_direct_wire_buffering,
        synth_splitnets = ctx.attr.synth_splitnets,
        synth_sizing = ctx.attr.synth_sizing,
        synth_hierarchy_mode = ctx.attr.synth_hierarchy_mode,
        synth_share_resources = ctx.attr.synth_share_resources,
        synth_adder_type = ctx.attr.synth_adder_type,
        synth_extra_mapping_file = ctx.file.synth_extra_mapping_file,
        synth_elaborate_only = ctx.attr.synth_elaborate_only,
        synth_elaborate_flatten = ctx.attr.synth_elaborate_flatten,
        synth_mul_booth = ctx.attr.synth_mul_booth,
        synth_tie_undefined = ctx.attr.synth_tie_undefined,
        synth_write_noattr = ctx.attr.synth_write_noattr,
        run_eqy = ctx.attr.run_eqy,
        eqy_script = ctx.file.eqy_script,
        eqy_force_accept_pdk = ctx.attr.eqy_force_accept_pdk,
    )]


librelane_synth_config = rule(
    implementation = _synth_config_impl,
    attrs = SYNTH_ATTRS,
    provides = [SynthConfig],
)
