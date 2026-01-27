# Verilator linting rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS")
load(":providers.bzl", "LibrelaneInfo")

def _lint_impl(ctx):
    return single_step_impl(ctx, "Verilator.Lint", step_outputs = [])

librelane_verilator_lint = rule(
    implementation = _lint_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
