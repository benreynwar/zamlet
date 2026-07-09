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
        "linter_error_on_multidriven": "Error on multiple-driver nets",
        "linter_defines": "Linter-specific preprocessor defines (list)",
        "linter_disable_warnings": "Verilator warning codes to disable globally",
        "linter_disable_warnings_blackbox": "Verilator warning codes to disable for blackbox models",
        "linter_vlt": "Extra Verilator configuration file",
        "extra_verilog_models": "Extra Verilog models (list of Files)",

        # Yosys config
        "synth_parameters": "Key-value pairs for Yosys chparam (list)",
        "use_slang": "Use Slang frontend for SystemVerilog",
        "slang_arguments": "Arguments passed to the Slang frontend",
        "synth_clockgate_min_width": "Minimum group size for clock-gating",
        "synth_corner": "Synthesis timing corner override",
        "synth_show": "Generate Yosys graphviz output",
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
        "synth_keep_hierarchy_min_cost": "Keep hierarchy for modules above estimated gate cost",
        "synth_keep_hierarchy_instances": "Instances to mark keep_hierarchy",
        "synth_keep_hierarchy_modules": "Modules to mark keep_hierarchy",
        "synth_share_resources": "Merge shareable resources",
        "synth_adder_type": "Adder mapping type",
        "synth_extra_mapping_file": "File - Extra techmap file",
        "synth_elaborate_only": "Elaborate without logic mapping",
        "synth_mul_booth": "Use Booth encoding for multipliers",
        "synth_tie_undefined": "Tie undefined values (high/low/empty)",
        "synth_write_noattr": "Omit Verilog attributes from netlist",
        "synth_normalize_single_bit_vectors": "Normalize [0:0] vectors to scalar wires",

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
    "linter_error_on_multidriven": attr.bool(
        doc = "Error on multiple-driver nets",
        default = True,
    ),
    "linter_defines": attr.string_list(
        doc = "Linter-specific preprocessor defines (overrides verilog_defines for lint)",
        default = [],
    ),
    "linter_disable_warnings": attr.string_list(
        doc = "Verilator warning codes disabled globally",
        default = ["DECLFILENAME", "EOFNEWLINE"],
    ),
    "linter_disable_warnings_blackbox": attr.string_list(
        doc = "Verilator warning codes disabled for blackbox models",
        default = ["UNDRIVEN", "UNUSEDSIGNAL"],
    ),
    "linter_vlt": attr.label(
        doc = "Extra Verilator configuration file",
        allow_single_file = True,
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
    "use_slang": attr.bool(
        doc = "Use Slang frontend for better SystemVerilog parsing",
        default = False,
    ),
    "slang_arguments": attr.string_list(
        doc = "Arguments passed to the Slang frontend",
        default = [],
    ),
    "synth_clockgate_min_width": attr.int(
        doc = "Clock-gate flip-flop groups at or above this width; 0 leaves unset",
        default = 0,
    ),
    "synth_corner": attr.string(
        doc = "Synthesis timing corner override; empty leaves unset",
        default = "",
    ),
    "synth_show": attr.bool(
        doc = "Generate Yosys graphviz output",
        default = False,
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
    "synth_keep_hierarchy_min_cost": attr.int(
        doc = "Mark modules above this estimated gate cost as keep_hierarchy; 0 leaves unset",
        default = 0,
    ),
    "synth_keep_hierarchy_instances": attr.string_list(
        doc = "Instances to mark keep_hierarchy",
        default = [],
    ),
    "synth_keep_hierarchy_modules": attr.string_list(
        doc = "Modules to mark keep_hierarchy",
        default = [],
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
    "synth_normalize_single_bit_vectors": attr.bool(
        doc = "Normalize [0:0] vectors to scalar wires",
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
    "linter_error_on_multidriven": True,
    "linter_defines": [],
    "linter_disable_warnings": ["DECLFILENAME", "EOFNEWLINE"],
    "linter_disable_warnings_blackbox": ["UNDRIVEN", "UNUSEDSIGNAL"],
    "linter_vlt": None,
    "extra_verilog_models": [],
    "synth_parameters": [],
    "use_slang": False,
    "slang_arguments": [],
    "synth_clockgate_min_width": 0,
    "synth_corner": "",
    "synth_show": False,
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
    "synth_keep_hierarchy_min_cost": 0,
    "synth_keep_hierarchy_instances": [],
    "synth_keep_hierarchy_modules": [],
    "synth_share_resources": True,
    "synth_adder_type": "YOSYS",
    "synth_extra_mapping_file": None,
    "synth_elaborate_only": False,
    "synth_mul_booth": False,
    "synth_tie_undefined": "low",
    "synth_write_noattr": True,
    "synth_normalize_single_bit_vectors": True,
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
        linter_error_on_multidriven = ctx.attr.linter_error_on_multidriven,
        linter_defines = ctx.attr.linter_defines,
        linter_disable_warnings = ctx.attr.linter_disable_warnings,
        linter_disable_warnings_blackbox = ctx.attr.linter_disable_warnings_blackbox,
        linter_vlt = ctx.file.linter_vlt,
        extra_verilog_models = ctx.files.extra_verilog_models,
        synth_parameters = ctx.attr.synth_parameters,
        use_slang = ctx.attr.use_slang,
        slang_arguments = ctx.attr.slang_arguments,
        synth_clockgate_min_width = ctx.attr.synth_clockgate_min_width,
        synth_corner = ctx.attr.synth_corner,
        synth_show = ctx.attr.synth_show,
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
        synth_keep_hierarchy_min_cost = ctx.attr.synth_keep_hierarchy_min_cost,
        synth_keep_hierarchy_instances = ctx.attr.synth_keep_hierarchy_instances,
        synth_keep_hierarchy_modules = ctx.attr.synth_keep_hierarchy_modules,
        synth_share_resources = ctx.attr.synth_share_resources,
        synth_adder_type = ctx.attr.synth_adder_type,
        synth_extra_mapping_file = ctx.file.synth_extra_mapping_file,
        synth_elaborate_only = ctx.attr.synth_elaborate_only,
        synth_mul_booth = ctx.attr.synth_mul_booth,
        synth_tie_undefined = ctx.attr.synth_tie_undefined,
        synth_write_noattr = ctx.attr.synth_write_noattr,
        synth_normalize_single_bit_vectors = ctx.attr.synth_normalize_single_bit_vectors,
        run_eqy = ctx.attr.run_eqy,
        eqy_script = ctx.file.eqy_script,
        eqy_force_accept_pdk = ctx.attr.eqy_force_accept_pdk,
    )]


librelane_synth_config = rule(
    implementation = _synth_config_impl,
    attrs = SYNTH_ATTRS,
    provides = [SynthConfig],
)
