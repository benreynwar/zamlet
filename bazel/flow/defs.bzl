# Public API for librelane Bazel flow rules

load(":providers.bzl", _LibrelaneInfo = "LibrelaneInfo", _PdkInfo = "PdkInfo", _MacroInfo = "MacroInfo")
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

# Providers
LibrelaneInfo = _LibrelaneInfo
PdkInfo = _PdkInfo
MacroInfo = _MacroInfo

# PDK
librelane_pdk = _librelane_pdk

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
