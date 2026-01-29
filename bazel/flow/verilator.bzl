# Verilator linting rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# Config keys used by Verilator.Lint step
# From librelane/steps/verilator.py config_vars and run() method
# Includes BASE_CONFIG_KEYS for librelane config loading
LINT_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # Input files
    "VERILOG_FILES",
    # Preprocessing (from config_vars)
    "VERILOG_INCLUDE_DIRS",
    "VERILOG_DEFINES",
    "VERILOG_POWER_DEFINE",
    # Linter behavior (from config_vars)
    "LINTER_INCLUDE_PDK_MODELS",
    "LINTER_RELATIVE_INCLUDES",
    "LINTER_ERROR_ON_LATCH",
    "LINTER_DEFINES",
    # Models (used in run())
    "CELL_VERILOG_MODELS",
    "EXTRA_VERILOG_MODELS",
]

def _lint_impl(ctx):
    return single_step_impl(ctx, "Verilator.Lint", LINT_CONFIG_KEYS, step_outputs = [])

librelane_verilator_lint = rule(
    implementation = _lint_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
