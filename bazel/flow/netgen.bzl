# Netgen LVS rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# Step 71: Netgen.LVS - netgen.py lines 127-253
# Config from LVS class (lines 141-153) and NetgenStep parent (lines 102-116)
NETGEN_LVS_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "LVS_INCLUDE_MARCO_NETLISTS",
    "LVS_FLATTEN_CELLS",
    "EXTRA_SPICE_MODELS",
    "MAGIC_EXT_USE_GDS",
    "NETGEN_SETUP",
    "CELL_SPICE_MODELS",
]

def _lvs_impl(ctx):
    return single_step_impl(ctx, "Netgen.LVS", NETGEN_LVS_CONFIG_KEYS, step_outputs = [])

librelane_netgen_lvs = rule(
    implementation = _lvs_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
