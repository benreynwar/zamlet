# Miscellaneous rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS")
load(":providers.bzl", "LibrelaneInfo")

def _report_manufacturability_impl(ctx):
    return single_step_impl(ctx, "Misc.ReportManufacturability", step_outputs = [])

librelane_report_manufacturability = rule(
    implementation = _report_manufacturability_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
