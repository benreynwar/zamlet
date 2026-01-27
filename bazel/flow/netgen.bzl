# Netgen LVS rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS")
load(":providers.bzl", "LibrelaneInfo")

def _lvs_impl(ctx):
    return single_step_impl(ctx, "Netgen.LVS", step_outputs = [])

librelane_netgen_lvs = rule(
    implementation = _lvs_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
