# Public API for librelane Bazel flow rules

load(":providers.bzl", _LibrelaneInfo = "LibrelaneInfo", _PdkInfo = "PdkInfo", _MacroInfo = "MacroInfo")
load("//bazel/flow/config:synth.bzl", _SynthConfig = "SynthConfig", _librelane_synth_config = "librelane_synth_config")
load("//bazel/flow/config:pnr.bzl", _PnRConfig = "PnRConfig", _librelane_pnr_config = "librelane_pnr_config")
load("//bazel/flow/config:signoff.bzl", _SignoffConfig = "SignoffConfig", _librelane_signoff_config = "librelane_signoff_config")
load(":pdk.bzl", _librelane_pdk = "librelane_pdk")
load(":init.bzl", _librelane_init = "librelane_init")
load(":synthesis.bzl", _librelane_synthesis = "librelane_synthesis")
load(":floorplan.bzl", _librelane_floorplan = "librelane_floorplan")
load(":place.bzl",
    _librelane_io_placement = "librelane_io_placement",
    _librelane_custom_io_placement = "librelane_custom_io_placement",
    _librelane_apply_def_template = "librelane_apply_def_template",
    _librelane_macro_placement = "librelane_macro_placement",
    _librelane_manual_macro_placement = "librelane_manual_macro_placement",
    _librelane_global_placement = "librelane_global_placement",
    _librelane_detailed_placement = "librelane_detailed_placement",
    _librelane_cts = "librelane_cts",
)
load(":route.bzl",
    _librelane_global_routing = "librelane_global_routing",
    _librelane_detailed_routing = "librelane_detailed_routing",
)
load(":sta.bzl",
    _librelane_sta_mid_pnr = "librelane_sta_mid_pnr",
    _librelane_sta_post_pnr = "librelane_sta_post_pnr",
)
load(":macro.bzl",
    _librelane_fill = "librelane_fill",
    _librelane_gds = "librelane_gds",
    _librelane_lef = "librelane_lef",
)
load(":full_flow.bzl",
    _librelane_classic_flow = "librelane_classic_flow",
)
load(":validate.bzl",
    _librelane_classic_bundled_flow = "librelane_classic_bundled_flow",
    _librelane_compare_flows_test = "librelane_compare_flows_test",
    _librelane_flow_inputs = "librelane_flow_inputs",
)

# Providers
LibrelaneInfo = _LibrelaneInfo
PdkInfo = _PdkInfo
MacroInfo = _MacroInfo
SynthConfig = _SynthConfig
PnRConfig = _PnRConfig
SignoffConfig = _SignoffConfig

# PDK
librelane_pdk = _librelane_pdk

# Config rules
librelane_synth_config = _librelane_synth_config
librelane_pnr_config = _librelane_pnr_config
librelane_signoff_config = _librelane_signoff_config

# Init (entry point)
librelane_init = _librelane_init

# Synthesis
librelane_synthesis = _librelane_synthesis

# Floorplan
librelane_floorplan = _librelane_floorplan

# Placement
librelane_io_placement = _librelane_io_placement
librelane_custom_io_placement = _librelane_custom_io_placement
librelane_apply_def_template = _librelane_apply_def_template
librelane_macro_placement = _librelane_macro_placement
librelane_manual_macro_placement = _librelane_manual_macro_placement
librelane_global_placement = _librelane_global_placement
librelane_detailed_placement = _librelane_detailed_placement
librelane_cts = _librelane_cts

# Routing
librelane_global_routing = _librelane_global_routing
librelane_detailed_routing = _librelane_detailed_routing

# STA
librelane_sta_mid_pnr = _librelane_sta_mid_pnr
librelane_sta_post_pnr = _librelane_sta_post_pnr

# Macro generation
librelane_fill = _librelane_fill
librelane_gds = _librelane_gds
librelane_lef = _librelane_lef

# Convenience macros
librelane_classic_flow = _librelane_classic_flow

# Validation
librelane_classic_bundled_flow = _librelane_classic_bundled_flow
librelane_compare_flows_test = _librelane_compare_flows_test
librelane_flow_inputs = _librelane_flow_inputs
