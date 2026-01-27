# KLayout rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS")
load(":providers.bzl", "LibrelaneInfo")

def _stream_out_impl(ctx):
    return single_step_impl(ctx, "KLayout.StreamOut", step_outputs = ["klayout_gds"])

def _xor_impl(ctx):
    return single_step_impl(ctx, "KLayout.XOR", step_outputs = [])

def _drc_impl(ctx):
    return single_step_impl(ctx, "KLayout.DRC", step_outputs = [])

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
