# Core attributes for librelane_init - the minimum required to run a flow
#
# These are the ~15 attributes that define the design identity.

load("//bazel/flow/providers:pdk.bzl", "PdkInfo")
load("//bazel/flow/providers:macro.bzl", "MacroInfo")

CORE_ATTRS = {
    "verilog_files": attr.label_list(
        doc = "Verilog/SystemVerilog source files",
        allow_files = [".v", ".sv"],
        mandatory = True,
    ),
    "top": attr.string(
        doc = "Top module name",
        mandatory = True,
    ),
    "clock_period": attr.string(
        doc = "Clock period in nanoseconds",
        default = "10.0",
    ),
    "clock_port": attr.string(
        doc = "Clock port name",
        default = "clock",
    ),
    "pdk": attr.label(
        doc = "PDK target providing PdkInfo",
        mandatory = True,
        providers = [PdkInfo],
    ),
    "macros": attr.label_list(
        doc = "Hard macro targets providing MacroInfo",
        default = [],
        providers = [MacroInfo],
    ),
    "pnr_sdc_file": attr.label(
        doc = "Custom SDC file for PnR timing constraints (optional)",
        allow_single_file = [".sdc"],
    ),
    "signoff_sdc_file": attr.label(
        doc = "Custom SDC file for signoff STA (optional)",
        allow_single_file = [".sdc"],
    ),
    "verilog_include_dirs": attr.string_list(
        doc = "Verilog include directories for `include directives",
        default = [],
    ),
    "verilog_defines": attr.string_list(
        doc = "Verilog preprocessor defines (e.g., 'FOO' or 'FOO=bar')",
        default = [],
    ),
}

# Default values for core fields in LibrelaneInput
CORE_DEFAULTS = {
    "clock_period": "10.0",
    "clock_port": "clock",
    "verilog_include_dirs": [],
    "verilog_defines": [],
}
