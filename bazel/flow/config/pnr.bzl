# Placement and routing configuration attributes and rule
#
# These ~80 attributes control floorplanning, placement, CTS, routing, and resizing.

PnRConfig = provider(
    doc = "Placement and routing configuration.",
    fields = {
        # Floorplan
        "fp_def_template": "File - DEF template for floorplan",
        "fp_pin_order_cfg": "File - Pin order config for custom IO placement",
        "fp_template_match_mode": "DEF template pin matching mode",
        "fp_template_copy_power_pins": "Copy power pins from DEF template",
        "fp_core_util": "Core utilization percentage",
        "fp_macro_horizontal_halo": "Horizontal halo around macros (um)",
        "fp_macro_vertical_halo": "Vertical halo around macros (um)",
        "fp_io_vextend": "Extend vertical IO pins outside die (um)",
        "fp_io_hextend": "Extend horizontal IO pins outside die (um)",
        "fp_io_vthickness_mult": "Vertical pin thickness multiplier",
        "fp_io_hthickness_mult": "Horizontal pin thickness multiplier",
        "fp_ppl_mode": "IO placement mode",
        "errors_on_unmatched_io": "Error on unmatched IO pins",

        # PDN
        "fp_pdn_skiptrim": "Skip metal trim step during pdngen",
        "fp_pdn_core_ring": "Enable core ring around design",
        "fp_pdn_enable_rails": "Enable rails in power grid",
        "fp_pdn_horizontal_halo": "Horizontal halo around macros for PDN (um)",
        "fp_pdn_vertical_halo": "Vertical halo around macros for PDN (um)",
        "fp_pdn_multilayer": "Use multiple layers in power grid",
        "fp_pdn_cfg": "File - Custom PDN configuration file",
        "pdn_connect_macros_to_grid": "Connect macros to top level power grid",
        "pdn_macro_connections": "Explicit macro power connections",
        "pdn_enable_global_connections": "Enable global PDN connections",
        "pdn_obstructions": "PDN obstructions (layer llx lly urx ury)",
        "routing_obstructions": "Routing obstructions (layer llx lly urx ury)",

        # Placement
        "pl_target_density_pct": "Target placement density percentage",
        "pl_skip_initial_placement": "Skip initial placement",
        "pl_wire_length_coef": "Wirelength coefficient",
        "pl_min_phi_coefficient": "Min phi coefficient",
        "pl_max_phi_coefficient": "Max phi coefficient",
        "pl_time_driven": "Time driven placement",
        "pl_routability_driven": "Routability driven placement",
        "pl_routability_overflow_threshold": "Routability overflow threshold",
        "pl_optimize_mirroring": "Run optimize_mirroring during detailed placement",
        "pl_max_displacement_x": "Max X displacement for placement (um)",
        "pl_max_displacement_y": "Max Y displacement for placement (um)",
        "manual_global_placements": "JSON dict of instance to placement",

        # CTS
        "cts_sink_clustering_size": "Max sinks per cluster",
        "cts_sink_clustering_max_diameter": "Max cluster diameter in um",
        "cts_clk_max_wire_length": "Max clock wire length in um",
        "cts_disable_post_processing": "Disable post-CTS outlier processing",
        "cts_distance_between_buffers": "Distance between buffers in um",
        "cts_corners": "IPVT corners for CTS",
        "cts_max_cap": "Max capacitance for CTS characterization in pF",
        "cts_max_slew": "Max slew for CTS characterization in ns",

        # Routing
        "rt_clock_min_layer": "Min clock routing layer",
        "rt_clock_max_layer": "Max clock routing layer",
        "grt_adjustment": "Global routing adjustment",
        "grt_macro_extension": "Macro blockage extension",
        "grt_allow_congestion": "Allow congestion during global routing",
        "grt_antenna_iters": "Max iterations for global antenna repairs",
        "grt_overflow_iters": "Max iterations for overflow convergence",
        "grt_antenna_margin": "Margin % to over-fix antenna violations",
        "drt_threads": "Threads for detailed routing",
        "drt_min_layer": "Override min layer for DRT",
        "drt_max_layer": "Override max layer for DRT",
        "drt_opt_iters": "Max optimization iterations",

        # Resizer
        "rsz_dont_touch_rx": "Regex for don't touch nets/instances",
        "rsz_dont_touch_list": "List of don't touch nets/instances",
        "rsz_corners": "IPVT corners for resizer",
        "design_repair_buffer_input_ports": "Buffer input ports during design repair",
        "design_repair_buffer_output_ports": "Buffer output ports during design repair",
        "design_repair_tie_fanout": "Repair tie cells fanout",
        "design_repair_tie_separation": "Allow tie separation",
        "design_repair_max_wire_length": "Max wire length for buffering (um)",
        "design_repair_max_slew_pct": "Slew margin percentage",
        "design_repair_max_cap_pct": "Capacitance margin percentage",
        "design_repair_remove_buffers": "Remove synthesis buffers",
        "pl_resizer_hold_slack_margin": "Hold slack margin in ns",
        "pl_resizer_setup_slack_margin": "Setup slack margin in ns",
        "pl_resizer_hold_max_buffer_pct": "Max hold buffers as % of instances",
        "pl_resizer_setup_max_buffer_pct": "Max setup buffers as % of instances",
        "pl_resizer_allow_setup_vios": "Allow setup violations when fixing hold",
        "pl_resizer_gate_cloning": "Enable gate cloning for setup fixes",
        "pl_resizer_fix_hold_first": "Fix hold before setup (experimental)",
        "grt_design_repair_run_grt": "Run GRT before/after resizer in post-GRT repair",
        "grt_design_repair_max_wire_length": "Max wire length for buffer insertion",
        "grt_design_repair_max_slew_pct": "Slew margin % during post-GRT repair",
        "grt_design_repair_max_cap_pct": "Cap margin % during post-GRT repair",
        "grt_resizer_hold_slack_margin": "Hold slack margin (ns)",
        "grt_resizer_setup_slack_margin": "Setup slack margin (ns)",
        "grt_resizer_hold_max_buffer_pct": "Max buffers for hold fixes (%)",
        "grt_resizer_setup_max_buffer_pct": "Max buffers for setup fixes (%)",
        "grt_resizer_allow_setup_vios": "Allow setup violations when fixing hold",
        "grt_resizer_gate_cloning": "Enable gate cloning for setup fixes",
        "grt_resizer_run_grt": "Run GRT after resizer steps",
        "grt_resizer_fix_hold_first": "Fix hold before setup (experimental)",

        # Diodes
        "diode_padding": "Diode cell padding in sites",
        "diode_on_ports": "Insert diodes on ports: none, in, out, both",

        # Misc
        "extra_excluded_cells": "Additional cells to exclude from PnR",
        "macro_placement_cfg": "Deprecated macro placement config",
    },
)

PNR_ATTRS = {
    # Floorplan
    "fp_def_template": attr.label(
        doc = "DEF file to use as floorplan template",
        allow_single_file = [".def"],
    ),
    "fp_pin_order_cfg": attr.label(
        doc = "Pin order configuration file for custom IO placement",
        allow_single_file = True,
    ),
    "fp_template_match_mode": attr.string(
        doc = "DEF template pin matching: strict or permissive",
        default = "strict",
        values = ["strict", "permissive"],
    ),
    "fp_template_copy_power_pins": attr.bool(
        doc = "Always copy power pins from DEF template",
        default = False,
    ),
    "fp_core_util": attr.string(
        doc = "Core utilization percentage (used if PL_TARGET_DENSITY_PCT not set)",
        default = "50",
    ),
    "fp_macro_horizontal_halo": attr.string(
        doc = "Horizontal halo size around macros while cutting rows (um)",
        default = "10",
    ),
    "fp_macro_vertical_halo": attr.string(
        doc = "Vertical halo size around macros while cutting rows (um)",
        default = "10",
    ),
    "fp_io_vextend": attr.string(
        doc = "Extend vertical IO pins outside die (um)",
        default = "0",
    ),
    "fp_io_hextend": attr.string(
        doc = "Extend horizontal IO pins outside die (um)",
        default = "0",
    ),
    "fp_io_vthickness_mult": attr.string(
        doc = "Vertical pin thickness multiplier (base is layer min width)",
        default = "2",
    ),
    "fp_io_hthickness_mult": attr.string(
        doc = "Horizontal pin thickness multiplier (base is layer min width)",
        default = "2",
    ),
    "fp_ppl_mode": attr.string(
        doc = "IO placement mode: matching, random_equidistant, or annealing",
        default = "matching",
    ),
    "errors_on_unmatched_io": attr.string(
        doc = "Error on unmatched IO pins: none, unmatched_design, unmatched_cfg, or both",
        default = "unmatched_design",
        values = ["none", "unmatched_design", "unmatched_cfg", "both"],
    ),

    # PDN
    "fp_pdn_skiptrim": attr.bool(
        doc = "Skip metal trim step during pdngen",
        default = False,
    ),
    "fp_pdn_core_ring": attr.bool(
        doc = "Enable adding a core ring around the design",
        default = False,
    ),
    "fp_pdn_enable_rails": attr.bool(
        doc = "Enable creation of rails in the power grid",
        default = True,
    ),
    "fp_pdn_horizontal_halo": attr.string(
        doc = "Horizontal halo around macros during PDN insertion (um)",
        default = "10",
    ),
    "fp_pdn_vertical_halo": attr.string(
        doc = "Vertical halo around macros during PDN insertion (um)",
        default = "10",
    ),
    "fp_pdn_multilayer": attr.bool(
        doc = "Use multiple layers in power grid (False for macro hardening)",
        default = True,
    ),
    "fp_pdn_cfg": attr.label(
        doc = "Custom PDN configuration file",
        allow_single_file = True,
    ),
    "pdn_connect_macros_to_grid": attr.bool(
        doc = "Enable connection of macros to top level power grid",
        default = True,
    ),
    "pdn_macro_connections": attr.string_list(
        doc = "Explicit macro power connections: instance_rx vdd_net gnd_net vdd_pin gnd_pin",
        default = [],
    ),
    "pdn_enable_global_connections": attr.bool(
        doc = "Enable creation of global connections in PDN generation",
        default = True,
    ),
    "pdn_obstructions": attr.string_list(
        doc = "PDN obstructions. Format: layer llx lly urx ury (um)",
        default = [],
    ),
    "routing_obstructions": attr.string_list(
        doc = "Routing obstructions. Format: layer llx lly urx ury (um)",
        default = [],
    ),

    # Placement
    "pl_target_density_pct": attr.string(
        doc = "Target placement density percentage (if empty, calculated dynamically)",
        default = "",
    ),
    "pl_skip_initial_placement": attr.bool(
        doc = "Skip initial placement in global placer",
        default = False,
    ),
    "pl_wire_length_coef": attr.string(
        doc = "Global placement initial wirelength coefficient",
        default = "0.25",
    ),
    "pl_min_phi_coefficient": attr.string(
        doc = "Lower bound on mu_k variable in GPL algorithm",
        default = "",
    ),
    "pl_max_phi_coefficient": attr.string(
        doc = "Upper bound on mu_k variable in GPL algorithm",
        default = "",
    ),
    "pl_time_driven": attr.bool(
        doc = "Use time driven placement in global placer",
        default = True,
    ),
    "pl_routability_driven": attr.bool(
        doc = "Use routability driven placement in global placer",
        default = True,
    ),
    "pl_routability_overflow_threshold": attr.string(
        doc = "Overflow threshold for routability mode",
        default = "",
    ),
    "pl_optimize_mirroring": attr.bool(
        doc = "Run optimize_mirroring pass during detailed placement",
        default = True,
    ),
    "pl_max_displacement_x": attr.string(
        doc = "Max X displacement when finding placement site (um)",
        default = "500",
    ),
    "pl_max_displacement_y": attr.string(
        doc = "Max Y displacement when finding placement site (um)",
        default = "100",
    ),
    "manual_global_placements": attr.string(
        doc = "JSON dict of instance name to placement {x, y, orientation}",
        default = "",
    ),

    # CTS
    "cts_sink_clustering_size": attr.int(
        doc = "Max sinks per cluster in CTS",
        default = 25,
    ),
    "cts_sink_clustering_max_diameter": attr.string(
        doc = "Max cluster diameter in um",
        default = "50",
    ),
    "cts_clk_max_wire_length": attr.string(
        doc = "Max clock wire length in um (0 = no limit)",
        default = "0",
    ),
    "cts_disable_post_processing": attr.bool(
        doc = "Disable post-CTS processing for outlier sinks",
        default = False,
    ),
    "cts_distance_between_buffers": attr.string(
        doc = "Distance between buffers in um (0 = auto)",
        default = "0",
    ),
    "cts_corners": attr.string_list(
        doc = "IPVT corners for CTS (empty = use STA_CORNERS)",
        default = [],
    ),
    "cts_max_cap": attr.string(
        doc = "Max capacitance for CTS characterization in pF (empty = from lib)",
        default = "",
    ),
    "cts_max_slew": attr.string(
        doc = "Max slew for CTS characterization in ns (empty = from lib)",
        default = "",
    ),

    # Routing
    "rt_clock_min_layer": attr.string(
        doc = "Lowest layer for clock net routing",
        default = "",
    ),
    "rt_clock_max_layer": attr.string(
        doc = "Highest layer for clock net routing",
        default = "",
    ),
    "grt_adjustment": attr.string(
        doc = "Global routing capacity reduction (0-1)",
        default = "0.3",
    ),
    "grt_macro_extension": attr.int(
        doc = "GCells added to macro blockage boundaries",
        default = 0,
    ),
    "grt_allow_congestion": attr.bool(
        doc = "Allow congestion during global routing",
        default = False,
    ),
    "grt_antenna_iters": attr.int(
        doc = "Maximum iterations for global antenna repairs",
        default = 3,
    ),
    "grt_overflow_iters": attr.int(
        doc = "Maximum iterations waiting for overflow to reach desired value",
        default = 50,
    ),
    "grt_antenna_margin": attr.int(
        doc = "Margin percentage to over-fix antenna violations",
        default = 10,
    ),
    "drt_threads": attr.int(
        doc = "Number of threads for detailed routing (0 = machine thread count)",
        default = 0,
    ),
    "drt_min_layer": attr.string(
        doc = "Override lowest layer for detailed routing",
        default = "",
    ),
    "drt_max_layer": attr.string(
        doc = "Override highest layer for detailed routing",
        default = "",
    ),
    "drt_opt_iters": attr.int(
        doc = "Max optimization iterations in TritonRoute",
        default = 64,
    ),

    # Resizer
    "rsz_dont_touch_rx": attr.string(
        doc = "Regex for nets/instances marked don't touch by resizer",
        default = "$^",
    ),
    "rsz_dont_touch_list": attr.string_list(
        doc = "List of nets/instances marked don't touch by resizer",
        default = [],
    ),
    "rsz_corners": attr.string_list(
        doc = "IPVT corners for resizer (empty = use STA_CORNERS)",
        default = [],
    ),
    "design_repair_buffer_input_ports": attr.bool(
        doc = "Insert buffers on input ports during design repair",
        default = True,
    ),
    "design_repair_buffer_output_ports": attr.bool(
        doc = "Insert buffers on output ports during design repair",
        default = True,
    ),
    "design_repair_tie_fanout": attr.bool(
        doc = "Repair tie cells fanout during design repair",
        default = True,
    ),
    "design_repair_tie_separation": attr.bool(
        doc = "Allow tie separation during design repair",
        default = False,
    ),
    "design_repair_max_wire_length": attr.string(
        doc = "Max wire length for buffer insertion during design repair (um, 0=disabled)",
        default = "0",
    ),
    "design_repair_max_slew_pct": attr.string(
        doc = "Slew margin percentage during design repair",
        default = "20",
    ),
    "design_repair_max_cap_pct": attr.string(
        doc = "Capacitance margin percentage during design repair",
        default = "20",
    ),
    "design_repair_remove_buffers": attr.bool(
        doc = "Remove synthesis buffers to give resizer more flexibility",
        default = False,
    ),
    "pl_resizer_hold_slack_margin": attr.string(
        doc = "Hold slack margin in ns for resizer timing optimization",
        default = "0.1",
    ),
    "pl_resizer_setup_slack_margin": attr.string(
        doc = "Setup slack margin in ns for resizer timing optimization",
        default = "0.05",
    ),
    "pl_resizer_hold_max_buffer_pct": attr.string(
        doc = "Max hold buffers as percentage of instances",
        default = "50",
    ),
    "pl_resizer_setup_max_buffer_pct": attr.string(
        doc = "Max setup buffers as percentage of instances",
        default = "50",
    ),
    "pl_resizer_allow_setup_vios": attr.bool(
        doc = "Allow setup violations when fixing hold violations",
        default = False,
    ),
    "pl_resizer_gate_cloning": attr.bool(
        doc = "Enable gate cloning when fixing setup violations",
        default = True,
    ),
    "pl_resizer_fix_hold_first": attr.bool(
        doc = "Fix hold violations before setup (experimental)",
        default = False,
    ),
    "grt_design_repair_run_grt": attr.bool(
        doc = "Run GRT before and after resizer during post-GRT repair",
        default = True,
    ),
    "grt_design_repair_max_wire_length": attr.string(
        doc = "Max wire length for buffer insertion during post-GRT repair (0 = no buffers)",
        default = "0",
    ),
    "grt_design_repair_max_slew_pct": attr.string(
        doc = "Slew margin percentage during post-GRT design repair",
        default = "10",
    ),
    "grt_design_repair_max_cap_pct": attr.string(
        doc = "Capacitance margin percentage during post-GRT design repair",
        default = "10",
    ),
    "grt_resizer_hold_slack_margin": attr.string(
        doc = "Time margin for hold slack when fixing violations (ns)",
        default = "0.05",
    ),
    "grt_resizer_setup_slack_margin": attr.string(
        doc = "Time margin for setup slack when fixing violations (ns)",
        default = "0.025",
    ),
    "grt_resizer_hold_max_buffer_pct": attr.string(
        doc = "Max buffers to insert for hold fixes (% of instances)",
        default = "50",
    ),
    "grt_resizer_setup_max_buffer_pct": attr.string(
        doc = "Max buffers to insert for setup fixes (% of instances)",
        default = "50",
    ),
    "grt_resizer_allow_setup_vios": attr.bool(
        doc = "Allow setup violations when fixing hold",
        default = False,
    ),
    "grt_resizer_gate_cloning": attr.bool(
        doc = "Enable gate cloning when fixing setup violations",
        default = True,
    ),
    "grt_resizer_run_grt": attr.bool(
        doc = "Run global routing after resizer steps",
        default = True,
    ),
    "grt_resizer_fix_hold_first": attr.bool(
        doc = "Experimental: fix hold before setup violations",
        default = False,
    ),

    # Diodes
    "diode_padding": attr.int(
        doc = "Diode cell padding in sites (increases width during placement checks)",
        default = 0,
    ),
    "diode_on_ports": attr.string(
        doc = "Insert diodes on ports: none, in, out, or both",
        default = "none",
        values = ["none", "in", "out", "both"],
    ),

    # Misc
    "extra_excluded_cells": attr.string_list(
        doc = "Additional cell wildcards to exclude from synthesis and PnR",
        default = [],
    ),
    "macro_placement_cfg": attr.label(
        doc = "Deprecated: Macro placement config file",
        allow_single_file = True,
    ),
}

# Default values for PnR config
PNR_DEFAULTS = {
    "fp_def_template": None,
    "fp_pin_order_cfg": None,
    "fp_template_match_mode": "strict",
    "fp_template_copy_power_pins": False,
    "fp_core_util": "50",
    "fp_macro_horizontal_halo": "10",
    "fp_macro_vertical_halo": "10",
    "fp_io_vextend": "0",
    "fp_io_hextend": "0",
    "fp_io_vthickness_mult": "2",
    "fp_io_hthickness_mult": "2",
    "fp_ppl_mode": "matching",
    "errors_on_unmatched_io": "unmatched_design",
    "fp_pdn_skiptrim": False,
    "fp_pdn_core_ring": False,
    "fp_pdn_enable_rails": True,
    "fp_pdn_horizontal_halo": "10",
    "fp_pdn_vertical_halo": "10",
    "fp_pdn_multilayer": True,
    "fp_pdn_cfg": None,
    "pdn_connect_macros_to_grid": True,
    "pdn_macro_connections": [],
    "pdn_enable_global_connections": True,
    "pdn_obstructions": [],
    "routing_obstructions": [],
    "pl_target_density_pct": "",
    "pl_skip_initial_placement": False,
    "pl_wire_length_coef": "0.25",
    "pl_min_phi_coefficient": "",
    "pl_max_phi_coefficient": "",
    "pl_time_driven": True,
    "pl_routability_driven": True,
    "pl_routability_overflow_threshold": "",
    "pl_optimize_mirroring": True,
    "pl_max_displacement_x": "500",
    "pl_max_displacement_y": "100",
    "manual_global_placements": "",
    "cts_sink_clustering_size": 25,
    "cts_sink_clustering_max_diameter": "50",
    "cts_clk_max_wire_length": "0",
    "cts_disable_post_processing": False,
    "cts_distance_between_buffers": "0",
    "cts_corners": [],
    "cts_max_cap": "",
    "cts_max_slew": "",
    "rt_clock_min_layer": "",
    "rt_clock_max_layer": "",
    "grt_adjustment": "0.3",
    "grt_macro_extension": 0,
    "grt_allow_congestion": False,
    "grt_antenna_iters": 3,
    "grt_overflow_iters": 50,
    "grt_antenna_margin": 10,
    "drt_threads": 0,
    "drt_min_layer": "",
    "drt_max_layer": "",
    "drt_opt_iters": 64,
    "rsz_dont_touch_rx": "$^",
    "rsz_dont_touch_list": [],
    "rsz_corners": [],
    "design_repair_buffer_input_ports": True,
    "design_repair_buffer_output_ports": True,
    "design_repair_tie_fanout": True,
    "design_repair_tie_separation": False,
    "design_repair_max_wire_length": "0",
    "design_repair_max_slew_pct": "20",
    "design_repair_max_cap_pct": "20",
    "design_repair_remove_buffers": False,
    "pl_resizer_hold_slack_margin": "0.1",
    "pl_resizer_setup_slack_margin": "0.05",
    "pl_resizer_hold_max_buffer_pct": "50",
    "pl_resizer_setup_max_buffer_pct": "50",
    "pl_resizer_allow_setup_vios": False,
    "pl_resizer_gate_cloning": True,
    "pl_resizer_fix_hold_first": False,
    "grt_design_repair_run_grt": True,
    "grt_design_repair_max_wire_length": "0",
    "grt_design_repair_max_slew_pct": "10",
    "grt_design_repair_max_cap_pct": "10",
    "grt_resizer_hold_slack_margin": "0.05",
    "grt_resizer_setup_slack_margin": "0.025",
    "grt_resizer_hold_max_buffer_pct": "50",
    "grt_resizer_setup_max_buffer_pct": "50",
    "grt_resizer_allow_setup_vios": False,
    "grt_resizer_gate_cloning": True,
    "grt_resizer_run_grt": True,
    "grt_resizer_fix_hold_first": False,
    "diode_padding": 0,
    "diode_on_ports": "none",
    "extra_excluded_cells": [],
    "macro_placement_cfg": None,
}


def _pnr_config_impl(ctx):
    return [PnRConfig(
        fp_def_template = ctx.file.fp_def_template,
        fp_pin_order_cfg = ctx.file.fp_pin_order_cfg,
        fp_template_match_mode = ctx.attr.fp_template_match_mode,
        fp_template_copy_power_pins = ctx.attr.fp_template_copy_power_pins,
        fp_core_util = ctx.attr.fp_core_util,
        fp_macro_horizontal_halo = ctx.attr.fp_macro_horizontal_halo,
        fp_macro_vertical_halo = ctx.attr.fp_macro_vertical_halo,
        fp_io_vextend = ctx.attr.fp_io_vextend,
        fp_io_hextend = ctx.attr.fp_io_hextend,
        fp_io_vthickness_mult = ctx.attr.fp_io_vthickness_mult,
        fp_io_hthickness_mult = ctx.attr.fp_io_hthickness_mult,
        fp_ppl_mode = ctx.attr.fp_ppl_mode,
        errors_on_unmatched_io = ctx.attr.errors_on_unmatched_io,
        fp_pdn_skiptrim = ctx.attr.fp_pdn_skiptrim,
        fp_pdn_core_ring = ctx.attr.fp_pdn_core_ring,
        fp_pdn_enable_rails = ctx.attr.fp_pdn_enable_rails,
        fp_pdn_horizontal_halo = ctx.attr.fp_pdn_horizontal_halo,
        fp_pdn_vertical_halo = ctx.attr.fp_pdn_vertical_halo,
        fp_pdn_multilayer = ctx.attr.fp_pdn_multilayer,
        fp_pdn_cfg = ctx.file.fp_pdn_cfg,
        pdn_connect_macros_to_grid = ctx.attr.pdn_connect_macros_to_grid,
        pdn_macro_connections = ctx.attr.pdn_macro_connections,
        pdn_enable_global_connections = ctx.attr.pdn_enable_global_connections,
        pdn_obstructions = ctx.attr.pdn_obstructions,
        routing_obstructions = ctx.attr.routing_obstructions,
        pl_target_density_pct = ctx.attr.pl_target_density_pct,
        pl_skip_initial_placement = ctx.attr.pl_skip_initial_placement,
        pl_wire_length_coef = ctx.attr.pl_wire_length_coef,
        pl_min_phi_coefficient = ctx.attr.pl_min_phi_coefficient,
        pl_max_phi_coefficient = ctx.attr.pl_max_phi_coefficient,
        pl_time_driven = ctx.attr.pl_time_driven,
        pl_routability_driven = ctx.attr.pl_routability_driven,
        pl_routability_overflow_threshold = ctx.attr.pl_routability_overflow_threshold,
        pl_optimize_mirroring = ctx.attr.pl_optimize_mirroring,
        pl_max_displacement_x = ctx.attr.pl_max_displacement_x,
        pl_max_displacement_y = ctx.attr.pl_max_displacement_y,
        manual_global_placements = ctx.attr.manual_global_placements,
        cts_sink_clustering_size = ctx.attr.cts_sink_clustering_size,
        cts_sink_clustering_max_diameter = ctx.attr.cts_sink_clustering_max_diameter,
        cts_clk_max_wire_length = ctx.attr.cts_clk_max_wire_length,
        cts_disable_post_processing = ctx.attr.cts_disable_post_processing,
        cts_distance_between_buffers = ctx.attr.cts_distance_between_buffers,
        cts_corners = ctx.attr.cts_corners,
        cts_max_cap = ctx.attr.cts_max_cap,
        cts_max_slew = ctx.attr.cts_max_slew,
        rt_clock_min_layer = ctx.attr.rt_clock_min_layer,
        rt_clock_max_layer = ctx.attr.rt_clock_max_layer,
        grt_adjustment = ctx.attr.grt_adjustment,
        grt_macro_extension = ctx.attr.grt_macro_extension,
        grt_allow_congestion = ctx.attr.grt_allow_congestion,
        grt_antenna_iters = ctx.attr.grt_antenna_iters,
        grt_overflow_iters = ctx.attr.grt_overflow_iters,
        grt_antenna_margin = ctx.attr.grt_antenna_margin,
        drt_threads = ctx.attr.drt_threads,
        drt_min_layer = ctx.attr.drt_min_layer,
        drt_max_layer = ctx.attr.drt_max_layer,
        drt_opt_iters = ctx.attr.drt_opt_iters,
        rsz_dont_touch_rx = ctx.attr.rsz_dont_touch_rx,
        rsz_dont_touch_list = ctx.attr.rsz_dont_touch_list,
        rsz_corners = ctx.attr.rsz_corners,
        design_repair_buffer_input_ports = ctx.attr.design_repair_buffer_input_ports,
        design_repair_buffer_output_ports = ctx.attr.design_repair_buffer_output_ports,
        design_repair_tie_fanout = ctx.attr.design_repair_tie_fanout,
        design_repair_tie_separation = ctx.attr.design_repair_tie_separation,
        design_repair_max_wire_length = ctx.attr.design_repair_max_wire_length,
        design_repair_max_slew_pct = ctx.attr.design_repair_max_slew_pct,
        design_repair_max_cap_pct = ctx.attr.design_repair_max_cap_pct,
        design_repair_remove_buffers = ctx.attr.design_repair_remove_buffers,
        pl_resizer_hold_slack_margin = ctx.attr.pl_resizer_hold_slack_margin,
        pl_resizer_setup_slack_margin = ctx.attr.pl_resizer_setup_slack_margin,
        pl_resizer_hold_max_buffer_pct = ctx.attr.pl_resizer_hold_max_buffer_pct,
        pl_resizer_setup_max_buffer_pct = ctx.attr.pl_resizer_setup_max_buffer_pct,
        pl_resizer_allow_setup_vios = ctx.attr.pl_resizer_allow_setup_vios,
        pl_resizer_gate_cloning = ctx.attr.pl_resizer_gate_cloning,
        pl_resizer_fix_hold_first = ctx.attr.pl_resizer_fix_hold_first,
        grt_design_repair_run_grt = ctx.attr.grt_design_repair_run_grt,
        grt_design_repair_max_wire_length = ctx.attr.grt_design_repair_max_wire_length,
        grt_design_repair_max_slew_pct = ctx.attr.grt_design_repair_max_slew_pct,
        grt_design_repair_max_cap_pct = ctx.attr.grt_design_repair_max_cap_pct,
        grt_resizer_hold_slack_margin = ctx.attr.grt_resizer_hold_slack_margin,
        grt_resizer_setup_slack_margin = ctx.attr.grt_resizer_setup_slack_margin,
        grt_resizer_hold_max_buffer_pct = ctx.attr.grt_resizer_hold_max_buffer_pct,
        grt_resizer_setup_max_buffer_pct = ctx.attr.grt_resizer_setup_max_buffer_pct,
        grt_resizer_allow_setup_vios = ctx.attr.grt_resizer_allow_setup_vios,
        grt_resizer_gate_cloning = ctx.attr.grt_resizer_gate_cloning,
        grt_resizer_run_grt = ctx.attr.grt_resizer_run_grt,
        grt_resizer_fix_hold_first = ctx.attr.grt_resizer_fix_hold_first,
        diode_padding = ctx.attr.diode_padding,
        diode_on_ports = ctx.attr.diode_on_ports,
        extra_excluded_cells = ctx.attr.extra_excluded_cells,
        macro_placement_cfg = ctx.file.macro_placement_cfg,
    )]


librelane_pnr_config = rule(
    implementation = _pnr_config_impl,
    attrs = PNR_ATTRS,
    provides = [PnRConfig],
)
