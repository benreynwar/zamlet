# KLayout rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInfo")

# KLayout.StreamOut config keys (KLayoutStep.config_vars + get_cli_args dependencies)
KLAYOUT_STREAMOUT_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # KLayoutStep PDK variables (klayout.py:33-52)
    "KLAYOUT_TECH",
    "KLAYOUT_PROPERTIES",
    "KLAYOUT_DEF_LAYER_MAP",
    # get_cli_args() dependencies (klayout.py:91-131)
    "EXTRA_LEFS",
    "EXTRA_GDS_FILES",
]

# KLayout.XOR config keys (XOR.config_vars)
KLAYOUT_XOR_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # KLayoutStep PDK variables
    "KLAYOUT_TECH",
    "KLAYOUT_PROPERTIES",
    "KLAYOUT_DEF_LAYER_MAP",
    # XOR-specific config (klayout.py:257-276)
    "KLAYOUT_XOR_THREADS",
    "KLAYOUT_XOR_IGNORE_LAYERS",
    "KLAYOUT_XOR_TILE_SIZE",
]

# KLayout.DRC config keys (DRC.config_vars)
KLAYOUT_DRC_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    # KLayoutStep PDK variables
    "KLAYOUT_TECH",
    "KLAYOUT_PROPERTIES",
    "KLAYOUT_DEF_LAYER_MAP",
    # DRC-specific config (klayout.py:349-369)
    "KLAYOUT_DRC_RUNSET",
    "KLAYOUT_DRC_OPTIONS",
    "KLAYOUT_DRC_THREADS",
    # Gating (classic.py:247-250)
    "RUN_KLAYOUT_DRC",
]

def _stream_out_impl(ctx):
    return single_step_impl(ctx, "KLayout.StreamOut", KLAYOUT_STREAMOUT_CONFIG_KEYS, step_outputs = ["klayout_gds"])

def _xor_impl(ctx):
    return single_step_impl(ctx, "KLayout.XOR", KLAYOUT_XOR_CONFIG_KEYS, step_outputs = [])

def _drc_impl(ctx):
    return single_step_impl(ctx, "KLayout.DRC", KLAYOUT_DRC_CONFIG_KEYS, step_outputs = [])

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
