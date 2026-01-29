# Netgen LVS rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# Netgen steps need BASE_CONFIG_KEYS for PDK info and design config
NETGEN_CONFIG_KEYS = BASE_CONFIG_KEYS

def _lvs_impl(ctx):
    return single_step_impl(ctx, "Netgen.LVS", NETGEN_CONFIG_KEYS, step_outputs = [])

librelane_netgen_lvs = rule(
    implementation = _lvs_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
