# Miscellaneous rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# Misc steps need BASE_CONFIG_KEYS for PDK info and design config
MISC_CONFIG_KEYS = BASE_CONFIG_KEYS

def _report_manufacturability_impl(ctx):
    return single_step_impl(ctx, "Misc.ReportManufacturability", MISC_CONFIG_KEYS, step_outputs = [])

librelane_report_manufacturability = rule(
    implementation = _report_manufacturability_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
