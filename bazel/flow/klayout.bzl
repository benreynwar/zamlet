# KLayout rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# KLayout steps need BASE_CONFIG_KEYS for PDK info and design config
KLAYOUT_CONFIG_KEYS = BASE_CONFIG_KEYS

def _stream_out_impl(ctx):
    return single_step_impl(ctx, "KLayout.StreamOut", KLAYOUT_CONFIG_KEYS, step_outputs = ["klayout_gds"])

def _xor_impl(ctx):
    return single_step_impl(ctx, "KLayout.XOR", KLAYOUT_CONFIG_KEYS, step_outputs = [])

def _drc_impl(ctx):
    return single_step_impl(ctx, "KLayout.DRC", KLAYOUT_CONFIG_KEYS, step_outputs = [])

librelane_klayout_stream_out = rule(
    implementation = _stream_out_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_klayout_xor = rule(
    implementation = _xor_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_klayout_drc = rule(
    implementation = _drc_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
